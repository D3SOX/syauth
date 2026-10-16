// SPDX-License-Identifier: MIT
import QtQuick
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support

PlasmaComponents3.Label {
    id: status

    // The installer supplies an absolute, shell-quoted CLI command.
    property string command: ""
    property string connectionState: "unknown"
    property bool polling: visible

    text: connectionState === "pending"
        ? qsTr("Waiting for approval on your phone. You can also enter your password.")
        : connectionState === "connected"
            ? qsTr("Phone connected — press Enter to request approval")
            : connectionState === "disconnected"
                ? qsTr("Phone disconnected — enter your password")
                : qsTr("Phone status unavailable — enter your password")
    textFormat: Text.PlainText
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.WordWrap
    Accessible.name: text

    function isSelectorPrompt(message) {
        return message.trim() === "Password, or press Enter to use your phone:";
    }

    function update(exitCode, output) {
        connectionState = "unknown";
        try {
            if (exitCode !== 0) return;
            const report = JSON.parse(output);
            if (report.daemon.state !== "up") return;
            const peers = report.daemon.peers;
            if (peers.some(peer => peer.in_flight_challenges > 0)) {
                connectionState = "pending";
            } else if (peers.some(peer => peer.connected === true)) {
                connectionState = "connected";
            } else if (peers.length === 0 || peers.every(peer => peer.connected === false)) {
                connectionState = "disconnected";
            }
        } catch (error) {
            connectionState = "unknown";
        }
        freshness.restart();
    }

    Plasma5Support.DataSource {
        id: probe
        engine: "executable"
        interval: 1000
        connectedSources: status.polling && status.command ? [status.command] : []
        onNewData: (sourceName, data) => {
            if (sourceName === status.command) status.update(data["exit code"], data["stdout"]);
        }
    }

    Timer {
        id: freshness
        interval: 3000
        onTriggered: status.connectionState = "unknown"
    }
}
