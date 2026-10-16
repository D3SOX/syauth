import QtQuick
import QtTest
import ".."

TestCase {
    name: "PhoneStatus"

    PhoneStatus { id: status; polling: false }

    function cleanup() {
        status.polling = false;
        status.command = "";
    }

    function test_polling_reads_live_command_changes() {
        status.command = "printf '%s' '" + report([{connected: true}]) + "'";
        status.polling = true;
        tryCompare(status, "connectionState", "connected", 3000);
        status.command = "printf '%s' '" + report([{connected: true, in_flight_challenges: 1}]) + "'";
        tryCompare(status, "connectionState", "pending", 3000);
        status.command = "printf '%s' '" + report([{connected: false}]) + "'";
        tryCompare(status, "connectionState", "disconnected", 3000);
    }

    function report(peers) {
        return JSON.stringify({daemon: {state: "up", peers: peers}});
    }

    function test_live_connection_changes() {
        status.update(0, report([{connected: true}]));
        compare(status.connectionState, "connected");
        verify(status.text.includes("press Enter"));
        status.update(0, report([{connected: false}]));
        compare(status.connectionState, "disconnected");
        verify(status.text.includes("enter your password"));
        status.update(0, report([{connected: true}]));
        compare(status.connectionState, "connected");
    }

    function test_pending_approval_and_return_to_idle() {
        status.update(0, report([{connected: true, in_flight_challenges: 1}]));
        compare(status.connectionState, "pending");
        verify(status.text.includes("Waiting for approval on your phone"));
        verify(status.text.includes("enter your password"));
        status.update(0, report([{connected: true, in_flight_challenges: 0}]));
        compare(status.connectionState, "connected");
        verify(status.text.includes("press Enter"));
        status.update(0, report([{connected: false, in_flight_challenges: 1}]));
        compare(status.connectionState, "pending");
        status.update(0, report([{connected: false, in_flight_challenges: 0}]));
        compare(status.connectionState, "disconnected");
    }

    function test_only_the_static_phone_instruction_is_replaced() {
        verify(status.isSelectorPrompt("Password, or press Enter to use your phone: "));
        verify(!status.isSelectorPrompt("Password: "));
        verify(!status.isSelectorPrompt("Unlocking failed"));
        verify(!status.isSelectorPrompt("Enter your smartcard PIN: "));
    }

    function test_unavailable_data() {
        return [
            {tag: "daemon down", code: 0, output: '{"daemon":{"state":"down"}}'},
            {tag: "invalid json", code: 0, output: 'invalid'},
            {tag: "process failed", code: 1, output: report([{connected: true}])},
            {tag: "older daemon", code: 0, output: report([{}])},
        ];
    }

    function test_unavailable(data) {
        status.update(0, report([{connected: true}]));
        status.update(0, report([{connected: true, in_flight_challenges: 1}]));
        status.update(data.code, data.output);
        compare(status.connectionState, "unknown");
        verify(status.text.includes("enter your password"));
    }

    function test_stale_status_expires_data() {
        return [{tag: "idle", active: 0}, {tag: "pending", active: 1}];
    }

    function test_stale_status_expires(data) {
        status.update(0, report([{connected: true, in_flight_challenges: data.active}]));
        tryCompare(status, "connectionState", "unknown", 4000);
    }
}
