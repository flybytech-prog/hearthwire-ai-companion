// A planted GTK module for tst_pluginpaths (never installed, never loaded by
// the app): when GTK loads it (GTK_PATH + GTK_MODULES, or GTK3_MODULES),
// it writes the file named in HW_PLANTED_GTK_MARKER. No GTK headers: the
// constructor runs on dlopen, before GTK looks for gtk_module_init.
#include <cstdio>
#include <cstdlib>

__attribute__((constructor)) static void hwPlantedGtkModuleLoaded()
{
    const char *marker = std::getenv("HW_PLANTED_GTK_MARKER");
    if (!marker)
        return;
    if (std::FILE *file = std::fopen(marker, "w"))
        std::fclose(file);
}

extern "C" __attribute__((visibility("default"))) void gtk_module_init(int *, char ***) {}
