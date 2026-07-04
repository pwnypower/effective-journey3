<?php
/**
 * mollie-relay.php — upload dit naar it-bosch.nl
 * Mollie stuurt hiernaartoe de webhook. Dit script verifieert de betaling
 * en slaat de status op zodat de HA-app hem kan ophalen.
 */

define('MOLLIE_API_KEY', 'JOUW_MOLLIE_API_KEY');   // live_xxx of test_xxx
define('STORAGE_FILE',   __DIR__ . '/mollie-updates.json');

// Alleen Mollie's eigen IP-reeksen mogen dit script aanroepen
$mollie_ips = ['87.233.217.', '205.201.128.', '185.93.116.', '213.249.'];
$remote = $_SERVER['REMOTE_ADDR'] ?? '';
$toegestaan = false;
foreach ($mollie_ips as $prefix) {
    if (str_starts_with($remote, $prefix)) { $toegestaan = true; break; }
}
// Sta ook localhost toe voor testen
if (!$toegestaan && !in_array($remote, ['127.0.0.1', '::1'])) {
    http_response_code(403);
    exit('Forbidden');
}

// Mollie stuurt: POST id=tr_xxxxxx
$id = $_POST['id'] ?? '';
if (!$id) {
    http_response_code(400);
    exit('Geen payment ID');
}

// Verifieer bij Mollie API
$ch = curl_init("https://api.mollie.com/v2/payments/" . urlencode($id));
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER     => ["Authorization: Bearer " . MOLLIE_API_KEY],
    CURLOPT_TIMEOUT        => 10,
]);
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($httpCode !== 200 || !$response) {
    http_response_code(500);
    exit('Mollie API fout');
}

$payment = json_decode($response, true);
if (!isset($payment['status'])) {
    http_response_code(500);
    exit('Ongeldig antwoord van Mollie');
}

// Lees bestaande updates
$updates = [];
if (file_exists(STORAGE_FILE)) {
    $updates = json_decode(file_get_contents(STORAGE_FILE), true) ?? [];
}

// Voeg toe (ook al bestaat hij, HA-app dedupliceert op payment_id)
$updates[] = [
    'payment_id' => $payment['id'],
    'status'     => $payment['status'],
    'amount'     => $payment['amount']['value'] ?? '0.00',
    'currency'   => $payment['amount']['currency'] ?? 'EUR',
    'factuur_id' => $payment['metadata']['factuur_id'] ?? null,
    'timestamp'  => date('c'),
    'claimed'    => false,
];

file_put_contents(STORAGE_FILE, json_encode($updates, JSON_PRETTY_PRINT));

http_response_code(200);
echo 'OK';
