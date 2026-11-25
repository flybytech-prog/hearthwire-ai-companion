# ctest: C++ unit tests (HelperCommand, ProcessRunner, ConfigStore,
# PlasmoidHost, ...) and the plasmoid's tests/qml under the stand-ins.
# Every test runs offscreen and never touches a session bus of the host:
# the bus tests (hw_bus_test) run on a private bus, all others see a dead
# address. The ProcessRunner test runs only a fake python3 it writes into a
# temp folder.
enable_testing()

set(hw_src ${CMAKE_CURRENT_SOURCE_DIR}/../src)
# No test may reach a real bus: every test gets a dead
# DBUS_SESSION_BUS_ADDRESS and DBUS_SYSTEM_BUS_ADDRESS (nothing listens there) and its own runtime
# folder in the build tree. The bus tests below run on a private bus.
set(hw_test_runtime ${CMAKE_BINARY_DIR}/test-runtime)
file(MAKE_DIRECTORY ${hw_test_runtime})
file(CHMOD ${hw_test_runtime} DIRECTORY_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE)
set(hw_test_env "QT_QPA_PLATFORM=offscreen;QT_QUICK_BACKEND=software;QT_QUICK_CONTROLS_MATERIAL_VARIANT=Dense"
    "DBUS_SESSION_BUS_ADDRESS=unix:path=${CMAKE_BINARY_DIR}/no-bus" "DBUS_SYSTEM_BUS_ADDRESS=unix:path=${CMAKE_BINARY_DIR}/no-bus"
    "XDG_RUNTIME_DIR=${hw_test_runtime}")

function(hw_test_target name)
    qt_add_executable(${name} ${name}.cpp)
    target_include_directories(${name} PRIVATE ${hw_src})
    target_compile_definitions(${name} PRIVATE
        HW_MAIN_XML="${HW_SYNCED}/main.xml"
        HW_REPO_SRC="${CMAKE_CURRENT_SOURCE_DIR}/../../src"
        HW_TEST_PYTHON="${HW_HELPER_PYTHON}")
    target_link_libraries(${name} PRIVATE Qt6::Test ${ARGN})
endfunction()

function(hw_test name)
    hw_test_target(${name} ${ARGN})
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endfunction()

# --- Bus tests (task 012 R3): each runs under its own dbus-run-session, on a
# private bus from dbus-session.conf (a path socket in the 0700 build-tree
# folder bus/, EXTERNAL auth, no service folders, no includes: nothing can be
# activated). Required: without dbus-run-session the configure fails rather
# than skipping them. Each test also checks its address (tests/BusGuard.h).
find_program(HW_DBUS_RUN_SESSION dbus-run-session REQUIRED)
find_program(HW_DBUS_DAEMON dbus-daemon REQUIRED)
set(HW_BUS_DIR ${CMAKE_BINARY_DIR}/bus)
# A unix socket path has at most 107 bytes; dbus adds /dbus-<10 random>.
string(LENGTH "${HW_BUS_DIR}/dbus-0123456789" hw_bus_path_length)
if(hw_bus_path_length GREATER 100)
    message(FATAL_ERROR "The build folder's path is too long for the test bus socket (${hw_bus_path_length} bytes); use a shorter one")
endif()
file(MAKE_DIRECTORY ${HW_BUS_DIR})
file(CHMOD ${HW_BUS_DIR} DIRECTORY_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE)
set(HW_BUS_CONFIG ${CMAKE_CURRENT_BINARY_DIR}/dbus-session.conf)
configure_file(dbus-session.conf.in ${HW_BUS_CONFIG} @ONLY)

function(hw_bus_test name)
    hw_test_target(${name} ${ARGN})
    target_link_libraries(${name} PRIVATE Qt6::DBus)
    target_compile_definitions(${name} PRIVATE HW_TEST_BUS_DIR="${HW_BUS_DIR}")
    add_test(NAME ${name} COMMAND ${HW_DBUS_RUN_SESSION} --config-file=${HW_BUS_CONFIG} --dbus-daemon=${HW_DBUS_DAEMON}
        -- $<TARGET_FILE:${name}>)
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endfunction()

hw_test(tst_helpercommand Qt6::Core)
target_sources(tst_helpercommand PRIVATE ${hw_src}/HelperCommand.h ${hw_src}/HelperCommand.cpp)
hw_test(tst_processrunner hwcompat_Plasma5Support Qt6::Qml)
hw_test(tst_configstore hwcompat_Plasmoid Qt6::Qml)
hw_test(tst_plasmoidhost hwcompat_Plasmoidplugin Qt6::Quick)
hw_test(tst_urlguard hwcompat_Plasmoidplugin Qt6::Quick Qt6::QuickControls2)
hw_test(tst_themewatcher hwcompat_Kirigamiplugin Qt6::Quick)
hw_test(tst_importtrust Qt6::Qml)
target_sources(tst_importtrust PRIVATE ${hw_src}/ImportTrust.h ${hw_src}/ImportTrust.cpp ${hw_src}/UrlGuard.h)
# BusGuard.h's own rows (no bus).
hw_test(tst_busguard Qt6::Core)
target_compile_definitions(tst_busguard PRIVATE HW_TEST_BUS_DIR="${HW_BUS_DIR}")
hw_bus_test(tst_notifier hwcompat_Notification)
hw_bus_test(tst_singleinstance Qt6::Qml)
target_sources(tst_singleinstance PRIVATE ${hw_src}/SingleInstance.h ${hw_src}/SingleInstance.cpp)
# The real binary, only ever as a second copy (the test owns the name first).
hw_bus_test(tst_secondlaunch)
add_dependencies(tst_secondlaunch hearthwire-hyprland)
target_compile_definitions(tst_secondlaunch PRIVATE HW_APP_BINARY="$<TARGET_FILE:hearthwire-hyprland>")
if(HW_FIXTURES)
    target_compile_definitions(tst_secondlaunch PRIVATE HW_APP_FIXTURES)
endif()

# AppTools (R4 P2b/P2c): present()'s steps and token order, About's values
# against plasmoid/metadata.json and the .desktop file. No bus.
hw_test(tst_apptools hwcompat_Plasmoidplugin hwcompat_Plasma5Support Qt6::Quick Qt6::QuickControls2 Qt6::DBus)
target_sources(tst_apptools PRIVATE ${hw_src}/AppTools.h ${hw_src}/AppTools.cpp
    ${hw_src}/SingleInstance.h ${hw_src}/SingleInstance.cpp)
target_include_directories(tst_apptools PRIVATE ${HW_GENERATED})
target_compile_definitions(tst_apptools PRIVATE
    HW_METADATA="${HW_PLASMOID}/metadata.json"
    HW_DESKTOP="${CMAKE_CURRENT_SOURCE_DIR}/../data/hearthwire-hyprland.desktop"
    HW_PROJECT_VERSION="${PROJECT_VERSION}")

# No way to open a URL or start another program from the app's own code or
# the QML it runs (decision-1 Q2: only the helper is started, and only
# through ProcessRunner), except the one reviewed chat-link opener: the
# synced LinkOut.js, exactly its bytes, directly in --synced (task 013 Q1 = B).
add_test(NAME app_starts_nothing_else COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_no_opener.py
    ${CMAKE_CURRENT_SOURCE_DIR}/../src ${CMAKE_CURRENT_SOURCE_DIR}/../qml --synced ${HW_SYNCED})
set_tests_properties(app_starts_nothing_else PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 60)
# Its own rows (review-7-security LOW-1): every pattern, fed from a scratch
# folder, is found; a clean control is not.
add_test(NAME app_starts_nothing_else_selftest COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_no_opener.py
    --self-test)
set_tests_properties(app_starts_nothing_else_selftest PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 60)

# Planted plugins for tst_pluginpaths (never installed, never loaded by the app).
# Test-only: the planted platform plugin needs Qt's private qpa/ headers, which
# some distributions package separately (qt6-base-private-dev and the like).
# Without them only the image-format half of tst_pluginpaths runs; the
# platform half skips.
set(QT_NO_PRIVATE_MODULE_WARNING ON)
find_package(Qt6 QUIET COMPONENTS GuiPrivate)
set(hw_planted ${CMAKE_CURRENT_BINARY_DIR}/planted)
add_library(hw_planted_image MODULE planted/ImagePlugin.cpp)
target_link_libraries(hw_planted_image PRIVATE Qt6::Gui)
set_target_properties(hw_planted_image PROPERTIES AUTOMOC ON LIBRARY_OUTPUT_DIRECTORY ${hw_planted}/plugins/imageformats)
# A planted GTK module (review-4 LOW-1), found through GTK_PATH/modules.
add_library(hw_planted_gtk MODULE planted/GtkModule.cpp)
set_target_properties(hw_planted_gtk PROPERTIES OUTPUT_NAME hwplantedgtk LIBRARY_OUTPUT_DIRECTORY ${hw_planted}/gtk/modules)
hw_test(tst_pluginpaths Qt6::Gui)
add_dependencies(tst_pluginpaths hw_planted_image hw_planted_gtk)
target_compile_definitions(tst_pluginpaths PRIVATE
    HW_PLANTED_PLUGINS="${hw_planted}/plugins" HW_PLANTED_PLATFORMS="${hw_planted}/platforms"
    HW_PLANTED_GTK="${hw_planted}/gtk")
if(TARGET Qt6::GuiPrivate)
    add_library(hw_planted_platform MODULE planted/PlatformPlugin.cpp)
    target_link_libraries(hw_planted_platform PRIVATE Qt6::Gui Qt6::GuiPrivate)
    set_target_properties(hw_planted_platform PROPERTIES AUTOMOC ON LIBRARY_OUTPUT_DIRECTORY ${hw_planted}/platforms)
    add_dependencies(tst_pluginpaths hw_planted_platform)
else()
    message(STATUS "Qt6 GuiPrivate not found: tst_pluginpaths skips its planted platform plugin half")
    target_compile_definitions(tst_pluginpaths PRIVATE HW_NO_PLANTED_PLATFORM)
endif()

# --- tests/qml, import lines pointed at the stand-ins and the synced plasmoid.
# All of them (tst_chat_web_view.qml with Qt WebEngine since task 013).
set(HW_QML_TEST_EXCLUDES)
set(HW_QMLTESTS ${CMAKE_BINARY_DIR}/qmltests)
set(hw_exclude_args)
foreach(name IN LISTS HW_QML_TEST_EXCLUDES)
    list(APPEND hw_exclude_args --exclude ${name})
endforeach()
execute_process(
    COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/../tools/sync_qml_tests.py
            --source ${CMAKE_CURRENT_SOURCE_DIR}/../../tests/qml --dest ${HW_QMLTESTS}
            --synced ${HW_SYNCED} ${hw_exclude_args} --list
    OUTPUT_VARIABLE hw_qml_tests
    RESULT_VARIABLE hw_qml_sync_result)
if(NOT hw_qml_sync_result EQUAL 0)
    message(FATAL_ERROR "sync_qml_tests.py failed")
endif()
file(GLOB hw_qml_test_inputs CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/../../tests/qml/*
    ${CMAKE_CURRENT_SOURCE_DIR}/../tools/sync_qml_tests.py)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${hw_qml_test_inputs})

# The views' ../images/ URLs, seen from the synced folder.
file(COPY ${HW_PLASMOID}/contents/images DESTINATION ${CMAKE_BINARY_DIR})
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/empty-book.json "[]\n")
qt_add_executable(hearthwire-qmltests qmltests.cpp ${hw_src}/LocalizedContext.h ${hw_src}/LocalizedContext.cpp
    ${hw_src}/IconProvider.h ${hw_src}/WebEngineEnv.h)
target_include_directories(hearthwire-qmltests PRIVATE ${hw_src})
target_compile_definitions(hearthwire-qmltests PRIVATE
    HW_MAIN_XML="${HW_SYNCED}/main.xml"
    HW_EMPTY_BOOK="${CMAKE_CURRENT_BINARY_DIR}/empty-book.json")
target_link_libraries(hearthwire-qmltests PRIVATE
    Qt6::QuickTest Qt6::Quick Qt6::QuickControls2 Qt6::DBus Qt6::WebEngineQuick
    hwcompat_Kirigamiplugin hwcompat_PlasmaComponentsplugin hwcompat_PlasmaExtrasplugin
    hwcompat_PlasmaCoreplugin hwcompat_Plasmoidplugin hwcompat_Plasma5Supportplugin
    hwcompat_KCMUtilsplugin hwcompat_Notificationplugin hwcompat_Configurationplugin hwstyleplugin)

string(REPLACE "\n" ";" hw_qml_tests "${hw_qml_tests}")
foreach(name IN LISTS hw_qml_tests)
    if(NOT name MATCHES "^tst_.*\\.qml$")
        continue()
    endif()
    get_filename_component(base ${name} NAME_WE)
    add_test(NAME qml_${base} COMMAND hearthwire-qmltests -input ${HW_QMLTESTS}/${name})
    set_tests_properties(qml_${base} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 180)
endforeach()

# The app's own QML tests of its stand-ins and style (tests/qml here).
file(GLOB hw_app_qml_tests CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/qml/tst_*.qml)
# Tests of the synced files themselves run from a copy next to the synced
# folder, so their "../synced/..." imports are the app's copies.
set(HW_APP_SYNCED_QML_TESTS tst_host.qml)
set(hw_app_synced_tests_dir ${CMAKE_BINARY_DIR}/apptests)
foreach(name IN LISTS HW_APP_SYNCED_QML_TESTS)
    list(REMOVE_ITEM hw_app_qml_tests ${CMAKE_CURRENT_SOURCE_DIR}/qml/${name})
    configure_file(qml/${name} ${hw_app_synced_tests_dir}/${name} COPYONLY)
    get_filename_component(base ${name} NAME_WE)
    add_test(NAME app_qml_${base} COMMAND hearthwire-qmltests -input ${hw_app_synced_tests_dir}/${name})
    set_tests_properties(app_qml_${base} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endforeach()
foreach(file IN LISTS hw_app_qml_tests)
    get_filename_component(base ${file} NAME_WE)
    add_test(NAME app_qml_${base} COMMAND hearthwire-qmltests -input ${file})
    set_tests_properties(app_qml_${base} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endforeach()
# The Notification stand-in's test: the Notifier in Record mode (nothing
# leaves the process; hearthwire-qmltests reads this one variable).
set_tests_properties(app_qml_tst_notification PROPERTIES ENVIRONMENT "${hw_test_env};HW_QMLTEST_NOTIFIER=record")

# The app itself refuses -platformpluginpath (review-4 LOW-2): one fixed
# line, exit 2, before Qt reads the argument.
set(hw_form 0)
foreach(form IN ITEMS "-platformpluginpath;/nonexistent" "--platformpluginpath;/nonexistent"
                      "-platformpluginpath=/nonexistent" "--platformpluginpath=/nonexistent")
    math(EXPR hw_form "${hw_form} + 1")
    set(id app_refuses_platformpluginpath_${hw_form})
    add_test(NAME ${id} COMMAND hearthwire-hyprland ${form})
    set_tests_properties(${id} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 30
        PASS_REGULAR_EXPRESSION "hearthwire-hyprland: -platformpluginpath is not accepted; Qt's plugins come only from Qt's own folder")
endforeach()

# Qt WebEngine (task 013): every QTWEBENGINE* variable is gone when
# initialize() runs, and Chromium switches on the app's command line end
# with exit 2 before anything of WebEngine starts (src/WebEngineEnv.h).
qt_add_executable(tst_webengineenv tst_webengineenv.cpp ${hw_src}/WebEngineEnv.h)
target_include_directories(tst_webengineenv PRIVATE ${hw_src})
target_link_libraries(tst_webengineenv PRIVATE Qt6::Test Qt6::Gui Qt6::WebEngineQuick)
add_dependencies(tst_webengineenv hearthwire-hyprland)
target_compile_definitions(tst_webengineenv PRIVATE HW_APP_BINARY="$<TARGET_FILE:hearthwire-hyprland>")
add_test(NAME tst_webengineenv COMMAND tst_webengineenv)
set_tests_properties(tst_webengineenv PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)

# The synced trees themselves, checked independently of the sync tools.
add_test(NAME synced_tree_has_no_kde
    COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_synced.py ${HW_SYNCED} ${HW_QMLTESTS})
set_tests_properties(synced_tree_has_no_kde PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 60)

# No RPATH/RUNPATH entry that is empty, relative or $ORIGIN-based
# (review-6-security LOW-1), in the build tree's binaries that ctest runs
# and (below) in the staged install. readelf is required, as dbus-run-session.
find_program(HW_READELF readelf REQUIRED)
add_test(NAME app_runpath COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_install.py
    --readelf ${HW_READELF} --runpath $<TARGET_FILE:hearthwire-hyprland> $<TARGET_FILE:hearthwire-qmltests>)
set_tests_properties(app_runpath PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 60)

# Install layout (R3.3): a staged `cmake --install --prefix /usr` holds
# exactly the binary and the .desktop file. A fixture build can't install.
if(NOT HW_FIXTURES)
    set(hw_stage ${CMAKE_BINARY_DIR}/stage)
    add_test(NAME app_install_layout COMMAND ${CMAKE_COMMAND} -E env DESTDIR=${hw_stage}
        sh -c "rm -rf -- \"$0\" && \"$1\" --install \"$2\" --prefix /usr >/dev/null && \"$3\" -I -B \"$4\" --stage \"$0\" --readelf \"$5\""
        ${hw_stage} ${CMAKE_COMMAND} ${CMAKE_BINARY_DIR} ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/check_install.py
        ${HW_READELF})
    set_tests_properties(app_install_layout PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120 RUN_SERIAL TRUE)
endif()
set(hw_desktop ${CMAKE_CURRENT_SOURCE_DIR}/../data/hearthwire-hyprland.desktop)
find_program(HW_DESKTOP_FILE_VALIDATE desktop-file-validate)
if(HW_DESKTOP_FILE_VALIDATE)
    add_test(NAME app_desktop_file_valid COMMAND sh -c "\"$0\" \"$1\" && \"$2\" -I -B \"$3\" --desktop \"$1\""
        ${HW_DESKTOP_FILE_VALIDATE} ${hw_desktop} ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/check_install.py)
else()
    add_test(NAME app_desktop_file_valid COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_install.py
        --desktop ${hw_desktop})
endif()
set_tests_properties(app_desktop_file_valid PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 60 FAIL_REGULAR_EXPRESSION "error:|warning:|FAIL")
