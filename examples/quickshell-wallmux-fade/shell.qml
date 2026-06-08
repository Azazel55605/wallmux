import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root

    // Match FADE_DURATION_MS in wallmux-fade.sh.
    property int fadeDuration: 250
    property color fadeColor: "#000000"
    property var coveredScreens: ({})
    property int stateRevision: 0

    function targetsMonitor(screenName, monitor) {
        if (monitor === "" || monitor === "all")
            return true;
        return monitor.split(",").map(name => name.trim()).includes(screenName);
    }

    function setCovered(monitor, covered) {
        for (const screen of Quickshell.screens) {
            if (targetsMonitor(screen.name, monitor))
                coveredScreens[screen.name] = covered;
        }
        stateRevision++;
    }

    function opacityFor(screenName) {
        stateRevision;
        return coveredScreens[screenName] ? 1.0 : 0.0;
    }

    IpcHandler {
        target: "wallmuxFade"

        function fadeIn(monitor: string): void {
            root.setCovered(monitor, true);
        }

        function fadeOut(monitor: string): void {
            root.setCovered(monitor, false);
        }
    }

    Variants {
        model: Quickshell.screens

        PanelWindow {
            id: overlay

            required property var modelData
            screen: modelData
            visible: true
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore
            mask: Region {}

            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.exclusiveZone: 0
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

            anchors {
                top: true
                bottom: true
                left: true
                right: true
            }

            Rectangle {
                anchors.fill: parent
                color: root.fadeColor
                opacity: root.opacityFor(overlay.modelData.name)

                Behavior on opacity {
                    NumberAnimation {
                        duration: root.fadeDuration
                        easing.type: Easing.InOutQuad
                    }
                }
            }
        }
    }
}
