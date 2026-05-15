<?php
/*
Standalone REDCap Sync for Vercel
Handles Data Entry Trigger (DET) webhooks.
*/

// ── Configuration via Environment Variables ──────────────────────────────────
$api_url = getenv('REDCAP_API_URL') ?: 'https://redcap.tch.harvard.edu/redcap_edc/api/';
$token = getenv('REDCAP_TOKEN') ?: '';
$secret = getenv('REDCAP_SECRET') ?: 'ca8318716dbf7cdc4682a6afebc6404c';
$python_bin = getenv('PYTHON_BIN') ?: 'python3';
$email_script = __DIR__ . '/generate_email_templ.py';

// ── Handle Request ──────────────────────────────────────────────────────────
$method = $_SERVER['REQUEST_METHOD'];
if ($method !== 'POST' && $method !== 'GET') {
    http_response_code(405);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => 'Method not allowed']);
    exit;
}

// Verify secret
$provided_secret = $_REQUEST['secret'] ?? '';
if (!hash_equals($secret, $provided_secret)) {
    http_response_code(403);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => 'Invalid secret']);
    exit;
}

if (empty($api_url) || empty($token)) {
    http_response_code(500);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => 'Configuration missing']);
    exit;
}

// ── Fetch Data from REDCap ──────────────────────────────────────────────────
$data = [
    'token' => $token,
    'content' => 'report',
    'format' => 'csv',
    'report_id' => '18198',
    'csvDelimiter' => '',
    'rawOrLabel' => 'raw',
    'rawOrLabelHeaders' => 'raw',
    'exportCheckboxLabel' => 'false',
    'returnFormat' => 'csv',
];

$ch = curl_init($api_url);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($data));
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($error) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => $error]);
    exit;
}

if ($http_code !== 200) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => 'REDCap API returned ' . $http_code]);
    exit;
}

// ── Save CSV ────────────────────────────────────────────────────────────────
$output_path = __DIR__ . '/redcap-data.csv';
if (file_put_contents($output_path, $response) === false) {
    http_response_code(500);
    header('Content-Type: application/json');
    echo json_encode(['status' => 'error', 'message' => 'Could not write file']);
    exit;
}

// ── Run Email Script ────────────────────────────────────────────────────────
$script_output = '';
$script_error = '';

if (file_exists($email_script)) {
    $cmd = escapeshellcmd($python_bin) . ' ' . escapeshellarg($email_script) . ' ' . escapeshellarg($output_path) . ' 2>&1';
    $script_output = shell_exec($cmd);
    if ($script_output === null) {
        $script_error = 'Script execution failed or is disabled.';
    }
} else {
    $script_error = 'Email script not found: ' . $email_script;
}

// ── Response ────────────────────────────────────────────────────────────────
header('Content-Type: application/json');
echo json_encode([
    'status' => 'ok',
    'updated' => gmdate('c'),
    'file' => $output_path,
    'triggered_by' => $_REQUEST['record'] ?? 'manual',
    'preview' => substr($response, 0, 500),
    'email_script' => basename($email_script),
    'script_output' => $script_output,
    'script_error' => $script_error ?: null,
]);
?>