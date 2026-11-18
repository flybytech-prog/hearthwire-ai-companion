# ctest: C++ unit tests (HelperCommand, ProcessRunner, ConfigStore,
# PlasmoidHost) and the plasmoid's tests/qml under the stand-ins.
# Every test runs offscreen and never touches a session bus; the
# ProcessRunner test runs only a fake python3 it writes into a temp folder.
enable_testing()

set(hw_src ${CMAKE_CURRENT_SOURCE_DIR}/../src)
set(hw_test_env "QT_QPA_PLATFORM=offscreen;QT_QUICK_BACKEND=software;QT_QUICK_CONTROLS_MATERIAL_VARIANT=Dense")

function(hw_test name)
    qt_add_executable(${name} ${name}.cpp)
    target_include_directories(${name} PRIVATE ${hw_src})
    target_compile_definitions(${name} PRIVATE
        HW_MAIN_XML="${HW_SYNCED}/main.xml"
        HW_REPO_SRC="${CMAKE_CURRENT_SOURCE_DIR}/../../src"
        HW_TEST_PYTHON="${HW_HELPER_PYTHON}")
    target_link_libraries(${name} PRIVATE Qt6::Test ${ARGN})
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endfunction()

hw_test(tst_helpercommand Qt6::Core)
target_sources(tst_helpercommand PRIVATE ${hw_src}/HelperCommand.h ${hw_src}/HelperCommand.cpp)
hw_test(tst_processrunner hwcompat_Plasma5Support Qt6::Qml)
hw_test(tst_configstore hwcompat_Plasmoid Qt6::Qml)
hw_test(tst_plasmoidhost hwcompat_Plasmoidplugin Qt6::Quick)
hw_test(tst_urlguard hwcompat_Plasmoidplugin Qt6::Quick Qt6::QuickControls2)
hw_test(tst_themewatcher hwcompat_Kirigamiplugin Qt6::Quick)

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
# Left out: tests that need more than the app has today.
#   tst_chat_web_view.qml  needs QtWebEngine (ChatWebView.qml; task 013).
set(HW_QML_TEST_EXCLUDES tst_chat_web_view.qml)
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
    ${hw_src}/IconProvider.h)
target_include_directories(hearthwire-qmltests PRIVATE ${hw_src})
target_compile_definitions(hearthwire-qmltests PRIVATE
    HW_MAIN_XML="${HW_SYNCED}/main.xml"
    HW_EMPTY_BOOK="${CMAKE_CURRENT_BINARY_DIR}/empty-book.json")
target_link_libraries(hearthwire-qmltests PRIVATE
    Qt6::QuickTest Qt6::Quick Qt6::QuickControls2
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
foreach(file IN LISTS hw_app_qml_tests)
    get_filename_component(base ${file} NAME_WE)
    add_test(NAME app_qml_${base} COMMAND hearthwire-qmltests -input ${file})
    set_tests_properties(app_qml_${base} PROPERTIES ENVIRONMENT "${hw_test_env}" TIMEOUT 120)
endforeach()

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

# The synced trees themselves, checked independently of the sync tools.
add_test(NAME synced_tree_has_no_kde
    COMMAND ${Python3_EXECUTABLE} -I -B ${CMAKE_CURRENT_SOURCE_DIR}/check_synced.py ${HW_SYNCED} ${HW_QMLTESTS})
set_tests_properties(synced_tree_has_no_kde PROPERTIES TIMEOUT 60)
