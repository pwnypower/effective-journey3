<?php
/**
 * mollie-relay.php — upload dit naar it-bosch.nl
 * Ontvangt Mollie's webhook en slaat het payment_id op.
 * De HA-app verifieert zelf bij Mollie of de betaling echt klopt.
 * Geen Mollie API-sleutel nodig in dit bestand.
 */

define('STORAGE_FILE', __DIR__ . '/mollie-updates.json');

// IP-check tijdelijk uitgeschakeld voor testen
// Zet dit terug aan na succesvolle test door de IP-reeksen van Mollie toe te voegen
// $remote = $_SERVER['REMOTE_ADDR'] ?? '';

// Mollie stuurt: POST id=tr_xxxxxx
$id = $_POST['id'] ?? '';
if (!$id || !str_starts_with($id, 'tr_')) {
    http_response_code(400);
    exit('Geen geldig payment ID');
}

// Sla alleen het payment_id op — verificatie doet de HA-app zelf via Mollie API
$updates = [];
if (file_exists(STORAGE_FILE)) {
    $updates = json_decode(file_get_contents(STORAGE_FILE), true) ?? [];
}

$updates[] = [
    'payment_id' => $id,
    'timestamp'  => date('c'),
    'claimed'    => false,
];

file_put_contents(STORAGE_FILE, json_encode($updates, JSON_PRETTY_PRINT));

http_response_code(200);
echo 'OK';
