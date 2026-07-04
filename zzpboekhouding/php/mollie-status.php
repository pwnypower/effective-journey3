<?php
/**
 * mollie-status.php — upload dit naar it-bosch.nl (zelfde map als mollie-relay.php)
 * De HA-app pollt dit elke 5 minuten om nieuwe betalingsupdates op te halen.
 * Na ophalen worden de updates als 'claimed' gemarkeerd.
 */

define('SECRET_TOKEN', 'VERVANG_DIT_MET_EEN_LANG_WILLEKEURIG_TOKEN');
define('STORAGE_FILE',  __DIR__ . '/mollie-updates.json');

// Controleer token
$token = $_GET['token'] ?? '';
if ($token !== SECRET_TOKEN) {
    http_response_code(403);
    exit('Forbidden');
}

// Lees updates
$updates = [];
if (file_exists(STORAGE_FILE)) {
    $updates = json_decode(file_get_contents(STORAGE_FILE), true) ?? [];
}

// Geef niet-geclaimde updates terug
$pending = array_values(array_filter($updates, fn($u) => !($u['claimed'] ?? false)));

// Markeer alle als claimed
foreach ($updates as &$u) {
    $u['claimed'] = true;
}
file_put_contents(STORAGE_FILE, json_encode(array_values($updates), JSON_PRETTY_PRINT));

header('Content-Type: application/json');
echo json_encode($pending);
