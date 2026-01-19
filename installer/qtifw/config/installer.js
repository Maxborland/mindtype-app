function Controller() {
    // Configure pages visibility - hide component selection (single component)
    installer.setDefaultPageVisible(QInstaller.ComponentSelection, false);
}

// No custom text overrides - let QtIFW use system locale translations
