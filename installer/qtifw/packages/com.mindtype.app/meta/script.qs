function Component() {
    // Default constructor
}

Component.prototype.createOperations = function() {
    // Call default implementation to copy files
    component.createOperations();

    if (systemInfo.productType === "windows") {
        // Create Start Menu shortcut
        component.addOperation("CreateShortcut", "@TargetDir@/MindType.exe", "@StartMenuDir@/MindType.lnk",
            "workingDirectory=@TargetDir@", "iconPath=@TargetDir@/MindType.exe",
            "description=Offline Voice Transcription");

        // Create Desktop shortcut
        component.addOperation("CreateShortcut", "@TargetDir@/MindType.exe", "@DesktopDir@/MindType.lnk",
            "workingDirectory=@TargetDir@", "iconPath=@TargetDir@/MindType.exe",
            "description=Offline Voice Transcription");
    }
}

