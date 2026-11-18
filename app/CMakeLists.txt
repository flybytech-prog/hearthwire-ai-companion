# hearthwire-hyprland: the plasmoid's QML in a plain Qt Quick (Material)
# app, through the private Hearthwire.Compat.* stand-ins (task 008 plan-v1
# §2.1-2.2). Task 012: single instance and notifications on the session bus,
# a .desktop file and install rules; no WebEngine yet (013).
#
# Build out of tree only, e.g.
#   cmake -S app -B "$TMPDIR/hw-app" -G Ninja && cmake --build "$TMPDIR/hw-app"
#   ctest --test-dir "$TMPDIR/hw-app" --output-on-failure
#
# Options:
#   HW_FIXTURES=ON   test build: the helper never runs, every command is
#                    answered from fixtures/; adds --config-dir/--shots/--checks.
#                    Never for a release.
#   HW_TESTS=ON      C++ unit tests and the tests/qml run under the stand-ins.
#   HW_HELPER_PYTHON the python3 the helper runs with (absolute; no PATH lookup).
#
# Install (release builds only; a fixture build refuses):
#   cmake --install <build> --prefix /usr
# installs exactly bin/hearthwire-hyprland and
# share/applications/hearthwire-hyprland.desktop. The icon "hearthwire" ships
# with hearthwire-helper, not here; tests and planted plugins never install.
cmake_minimum_required(VERSION 3.21)
project(hearthwire-hyprland VERSION 1.2.0 LANGUAGES CXX)
include(GNUInstallDirs)

if(CMAKE_BINARY_DIR STREQUAL CMAKE_SOURCE_DIR)
    message(FATAL_ERROR "Build out of tree (for example in $TMPDIR).")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(HW_FIXTURES "Test build answering from fixtures; the helper never runs" OFF)
option(HW_TESTS "Build the unit tests and the QML test runner" ON)
set(HW_HELPER_PYTHON "/usr/bin/python3" CACHE STRING "Absolute path of the python3 that runs the helper")
if(NOT IS_ABSOLUTE "${HW_HELPER_PYTHON}")
    message(FATAL_ERROR "HW_HELPER_PYTHON must be an absolute path")
endif()

set(hw_qt_components Gui Qml Quick QuickControls2 DBus)
if(HW_TESTS)
    list(APPEND hw_qt_components Test QuickTest)
endif()
find_package(Qt6 6.8 REQUIRED COMPONENTS ${hw_qt_components})
find_package(Python3 REQUIRED COMPONENTS Interpreter)
qt_standard_project_setup(REQUIRES 6.8)
# No RUNPATH at all (review-6-security LOW-1). qt_standard_project_setup()
# sets the install RPATH to $ORIGIN:$ORIGIN/../lib, and CMake pads the
# build-tree RUNPATH with ':' to that length for the install rewrite: empty
# entries, which ld.so reads as the current folder. The app has no libraries
# of its own; every one it needs is in the system's folders.
set(CMAKE_INSTALL_RPATH "")
qt_policy(SET QTP0004 NEW)

# Every QML module lands in build/qml/<URI path>, which tooling also reads.
set(QT_QML_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/qml)

set(HW_PLASMOID ${CMAKE_CURRENT_SOURCE_DIR}/../plasmoid)
set(HW_SYNCED ${CMAKE_BINARY_DIR}/synced)

# --- The plasmoid's files, import lines rewritten (tools/sync_plasmoid.py).
# ChatWebView.qml needs Qt WebEngine, which the spike leaves out.
execute_process(
    COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/tools/sync_plasmoid.py
            --source ${HW_PLASMOID} --dest ${HW_SYNCED} --exclude ChatWebView.qml --list
    OUTPUT_VARIABLE hw_synced_names
    RESULT_VARIABLE hw_sync_result)
if(NOT hw_sync_result EQUAL 0)
    message(FATAL_ERROR "sync_plasmoid.py failed")
endif()
file(GLOB hw_plasmoid_inputs CONFIGURE_DEPENDS
    ${HW_PLASMOID}/contents/ui/* ${HW_PLASMOID}/contents/config/*
    ${CMAKE_CURRENT_SOURCE_DIR}/tools/sync_plasmoid.py)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${hw_plasmoid_inputs})

string(REPLACE "\n" ";" hw_synced_names "${hw_synced_names}")
set(hw_plasmoid_qml)
set(hw_plasmoid_resources)
foreach(name IN LISTS hw_synced_names)
    if(name STREQUAL "")
        continue()
    endif()
    set(file ${HW_SYNCED}/${name})
    set_source_files_properties(${file} PROPERTIES QT_RESOURCE_ALIAS ${name})
    if(name MATCHES "\\.(qml|js)$")
        list(APPEND hw_plasmoid_qml ${file})
    else()
        list(APPEND hw_plasmoid_resources ${file})
    endif()
endforeach()

qt_add_qml_module(hwplasmoid
    URI Hearthwire.Plasmoid
    VERSION 1.0
    STATIC
    QML_FILES ${hw_plasmoid_qml}
    RESOURCES ${hw_plasmoid_resources})

# --- Stand-in modules: app/qml/Hearthwire/Compat/<name>/*.qml plus C++.
function(hw_compat name)
    set(dir ${CMAKE_CURRENT_SOURCE_DIR}/qml/Hearthwire/Compat/${name})
    file(GLOB qml_files CONFIGURE_DEPENDS ${dir}/*.qml)
    foreach(file IN LISTS qml_files)
        get_filename_component(base ${file} NAME)
        set_source_files_properties(${file} PROPERTIES QT_RESOURCE_ALIAS ${base})
        if(base STREQUAL "Units.qml")
            set_source_files_properties(${file} PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
        endif()
    endforeach()
    qt_add_qml_module(hwcompat_${name}
        URI Hearthwire.Compat.${name}
        VERSION 1.0
        STATIC
        QML_FILES ${qml_files}
        SOURCES ${ARGN})
    target_include_directories(hwcompat_${name} PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(hwcompat_${name} PRIVATE Qt6::Quick Qt6::QuickControls2)
endfunction()

hw_compat(Kirigami src/KirigamiCompat.h src/KirigamiCompat.cpp src/ThemeWatcher.h src/ThemeWatcher.cpp)
hw_compat(PlasmaComponents)
hw_compat(PlasmaExtras)
hw_compat(PlasmaCore)
hw_compat(Plasmoid src/PlasmoidHost.h src/PlasmoidHost.cpp src/ConfigStore.h src/ConfigStore.cpp)
hw_compat(Plasma5Support src/ProcessRunner.h src/ProcessRunner.cpp src/HelperCommand.h src/HelperCommand.cpp)
target_compile_definitions(hwcompat_Plasma5Support PRIVATE HW_HELPER_PYTHON="${HW_HELPER_PYTHON}")
hw_compat(KCMUtils)
hw_compat(Notification src/Notifier.h src/Notifier.cpp)
target_link_libraries(hwcompat_Notification PUBLIC Qt6::DBus)
hw_compat(Configuration)

# --- The app's Qt Quick Controls style: Material, with the few controls that
# need Kirigami's sizing (QQuickStyle::setStyle in main.cpp).
set_source_files_properties(qml/Hearthwire/Style/ComboBox.qml PROPERTIES QT_RESOURCE_ALIAS ComboBox.qml)
# QtQuick.Controls imports the style with its own version and the style
# passes it on to Material (`auto`), so the module is versioned as Qt is.
qt_add_qml_module(hwstyle
    URI Hearthwire.Style
    VERSION 6.0
    STATIC
    QML_FILES qml/Hearthwire/Style/ComboBox.qml
    IMPORTS QtQuick.Controls.Material/auto)
target_link_libraries(hwstyle PRIVATE Qt6::Quick Qt6::QuickControls2)

# --- The app.
qt_add_executable(hearthwire-hyprland
    src/main.cpp
    src/LocalizedContext.h src/LocalizedContext.cpp
    src/IconProvider.h
    src/ImportPaths.h
    src/ImportTrust.h src/ImportTrust.cpp
    src/UrlGuard.h)

file(GLOB hw_app_qml CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/qml/Hearthwire/App/*.qml)
if(NOT HW_FIXTURES)
    list(FILTER hw_app_qml EXCLUDE REGEX "/SpikeChecks\\.qml$")
endif()
foreach(file IN LISTS hw_app_qml)
    get_filename_component(base ${file} NAME)
    set_source_files_properties(${file} PROPERTIES QT_RESOURCE_ALIAS ${base})
endforeach()
qt_add_qml_module(hearthwire-hyprland
    URI Hearthwire.App
    VERSION 1.0
    DEPENDENCIES Hearthwire.Compat.Plasmoid
    QML_FILES ${hw_app_qml}
    SOURCES src/AppTools.h src/AppTools.cpp src/SingleInstance.h src/SingleInstance.cpp)
target_include_directories(hearthwire-hyprland PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_definitions(hearthwire-hyprland PRIVATE HW_VERSION="${PROJECT_VERSION}")

if(HW_FIXTURES)
    target_compile_definitions(hearthwire-hyprland PRIVATE HW_FIXTURES)
    qt_add_resources(hearthwire-hyprland fixtures
        PREFIX /hearthwire/fixtures
        BASE fixtures
        FILES fixtures/replies.json fixtures/snapshot.json)
endif()

target_link_libraries(hearthwire-hyprland PRIVATE
    Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2 Qt6::DBus
    hwplasmoidplugin hwstyleplugin
    hwcompat_Kirigamiplugin hwcompat_PlasmaComponentsplugin hwcompat_PlasmaExtrasplugin
    hwcompat_PlasmaCoreplugin hwcompat_Plasmoidplugin hwcompat_Plasma5Supportplugin
    hwcompat_KCMUtilsplugin hwcompat_Notificationplugin hwcompat_Configurationplugin)

# The plasmoid's own images, where its ../images/ URLs point.
file(GLOB hw_images CONFIGURE_DEPENDS ${HW_PLASMOID}/contents/images/*)
qt_add_resources(hearthwire-hyprland plasmoid_images
    PREFIX /qt/qml/Hearthwire/images
    BASE ${HW_PLASMOID}/contents/images
    FILES ${hw_images})

# --- Install: the binary and its .desktop file (its name is the app id,
# setDesktopFileName and the notifications' desktop-entry hint).
if(HW_FIXTURES)
    install(CODE "message(FATAL_ERROR \"A fixture build (HW_FIXTURES=ON) is for tests only and can't be installed\")")
else()
    install(TARGETS hearthwire-hyprland RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
    install(FILES data/hearthwire-hyprland.desktop DESTINATION ${CMAKE_INSTALL_DATADIR}/applications
        PERMISSIONS OWNER_READ OWNER_WRITE GROUP_READ WORLD_READ)
endif()

if(HW_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
