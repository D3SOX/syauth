//! A password winning must release the phone challenge slot immediately.

use std::{path::PathBuf, sync::Arc, time::Duration};

use syauth_core::{Bond, BondStatus, peer_id_from_pubkey};
use syauth_presenced::{Orchestrator, Request, ServeConfig, serve, write_frame};
use syauth_transport::FakePeripheral;
use time::OffsetDateTime;
use tokio::{
    net::UnixStream,
    sync::oneshot,
    time::{Instant, sleep, timeout},
};

#[tokio::test]
async fn disconnect_releases_the_phone_slot_before_the_approval_timeout() {
    let directory = tempfile::tempdir().unwrap();
    let socket = directory.path().join("auth.sock");
    let peer_id = peer_id_from_pubkey(&[1; 32]);
    let bond = Bond {
        peer_id: peer_id.clone(),
        pubkey: [1; 32],
        name: "phone".into(),
        created_at: OffsetDateTime::UNIX_EPOCH,
        status: BondStatus::Bonded,
    };
    let fake = FakePeripheral::new();
    let orchestrator = Arc::new(Orchestrator::with_peers_and_audit(
        fake.clone(),
        vec![(bond, [1; 32])],
        PathBuf::new(),
        PathBuf::new(),
        Instant::now() + Duration::from_secs(60),
        None,
    ));
    use syauth_transport::Peripheral;
    fake.add_peer(&peer_id, &[1; 32]).await.unwrap();
    let (stop, stopped) = oneshot::channel();
    let config = ServeConfig {
        socket_path: socket.clone(),
        expected_uid: None,
        reload_tx: None,
        orchestrator: Some(orchestrator.clone()),
        test_fixed_nonce: None,
        started_at: None,
    };
    let server = tokio::spawn(serve(config, async {
        let _ = stopped.await;
    }));
    timeout(Duration::from_secs(2), async {
        while !socket.exists() {
            sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    let mut client = UnixStream::connect(&socket).await.unwrap();
    write_frame(
        &mut client,
        &Request::Challenge {
            peer_id: peer_id.clone(),
            nonce: vec![1; 16],
        },
    )
    .await
    .unwrap();
    timeout(Duration::from_secs(2), async {
        while fake.notify_calls().is_empty() {
            sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(orchestrator.peers_snapshot().await[0].in_flight_challenges, 1);
    drop(client);
    let released = timeout(Duration::from_secs(1), async {
        while orchestrator.peers_snapshot().await[0].in_flight_challenges != 0 {
            sleep(Duration::from_millis(5)).await;
        }
    })
    .await;
    stop.send(()).unwrap();
    server.await.unwrap().unwrap();
    assert!(released.is_ok(), "closed password/phone race must not leave the phone slot busy");
    let notifications = fake.notify_calls();
    assert_eq!(notifications.len(), 2, "phone must receive a cancellation after the challenge");
    let challenge = syauth_core::Frame::decode(&notifications[0].1).unwrap();
    let cancel = syauth_core::Frame::decode(&notifications[1].1).unwrap();
    assert_eq!(cancel.nonce, challenge.nonce, "cancellation identifies the exact pending approval");
    assert_eq!(cancel.payload, b"cancel");
    assert!(syauth_core::verify_tag(&[1; 32], &cancel.body_bytes().unwrap(), &cancel.tag));
}
