<?php
/*
Plugin Name: REDCap Sync
Description: Sync REDCap data via API. Fires on REDCap Data Entry Trigger (DET).
Version: 1.1
*/

// ── Settings page ──────────────────────────────────────────────────────────────

add_action('admin_menu', function () {
    add_options_page('REDCap Sync', 'REDCap Sync', 'manage_options', 'redcap-sync', 'redcap_sync_settings_page');
});

add_action('admin_init', function () {
    register_setting('redcap_sync_options', 'redcap_sync_api_url',       ['sanitize_callback' => 'esc_url_raw']);
    register_setting('redcap_sync_options', 'redcap_sync_token',         ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('redcap_sync_options', 'redcap_sync_secret',        ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('redcap_sync_options', 'redcap_sync_python_bin',    ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('redcap_sync_options', 'redcap_sync_email_script',  ['sanitize_callback' => 'sanitize_text_field']);
});

function redcap_sync_settings_page() {
    $webhook_url = home_url('/?rest_route=/redcap/v1/update&secret=') . esc_attr(get_option('redcap_sync_secret', ''));
    ?>
    <div class="wrap">
        <h1>REDCap Sync Settings</h1>
        <form method="post" action="options.php">
            <?php settings_fields('redcap_sync_options'); ?>
            <table class="form-table">
                <tr>
                    <th>REDCap API URL</th>
                    <td><input type="url" name="redcap_sync_api_url" class="regular-text"
                        value="<?php echo esc_attr(get_option('redcap_sync_api_url', 'https://redcap.tch.harvard.edu/redcap_edc/api/')); ?>" /></td>
                </tr>
                <tr>
                    <th>REDCap API Token</th>
                    <td><input type="password" name="redcap_sync_token" class="regular-text"
                        placeholder="E0CA32DDA744F69007F290643B9C0EAC"
                        value="<?php echo esc_attr(get_option('redcap_sync_token', '')); ?>" /></td>
                </tr>
                <tr>
                    <th>Webhook Secret</th>
                    <td>
                        <input type="text" name="redcap_sync_secret" class="regular-text"
                            value="<?php echo esc_attr(get_option('redcap_sync_secret', 'ca8318716dbf7cdc4682a6afebc6404c')); ?>" />
                        <p class="description">A random string you create. Add it to the REDCap Data Entry Trigger URL below.</p>
                    </td>
                </tr>
                <tr>
                    <th>Python Executable</th>
                    <td><input type="text" name="redcap_sync_python_bin" class="regular-text"
                        placeholder="/usr/bin/python3"
                        value="<?php echo esc_attr(get_option('redcap_sync_python_bin', 'python3')); ?>" />
                        <p class="description">Path to the Python interpreter on the server (e.g. <code>python3</code> or <code>/usr/bin/python3</code>).</p>
                    </td>
                </tr>
                <tr>
                    <th>Email Script Path</th>
                    <td><input type="text" name="redcap_sync_email_script" class="regular-text"
                        placeholder="/path/to/generate_email_templ.py"
                        value="<?php echo esc_attr(get_option('redcap_sync_email_script', '')); ?>" />
                        <p class="description">Absolute path to <code>generate_email_templ.py</code> on the server. Run on every successful DET sync.</p>
                    </td>
                </tr>
                <tr>
                    <th>Data Entry Trigger URL</th>
                    <td>
                        <code><?php echo esc_html($webhook_url); ?></code>
                        <p class="description">Paste this URL into REDCap &rarr; Project Setup &rarr; Additional Customizations &rarr; Data Entry Trigger.</p>
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

// ── REST endpoint ──────────────────────────────────────────────────────────────

add_action('rest_api_init', function () {
    register_rest_route('redcap/v1', '/update', array(
        'methods'             => 'POST',
        'callback'            => 'redcap_update',
        'permission_callback' => 'redcap_verify_secret',
    ));
    register_rest_route('redcap/v1', '/data', array(
        'methods'             => 'POST',
        'callback'            => 'redcap_serve_data',
        'permission_callback' => '__return_true',
    ));
});

function redcap_verify_secret(WP_REST_Request $request) {
    $saved_secret = get_option('redcap_sync_secret', 'ca8318716dbf7cdc4682a6afebc6404c');
    if (empty($saved_secret)) {
        return new WP_Error('no_secret', 'Webhook secret not configured.', ['status' => 403]);
    }
    $provided = $request->get_param('secret');
    if (!hash_equals($saved_secret, (string) $provided)) {
        return new WP_Error('forbidden', 'Invalid secret.', ['status' => 403]);
    }
    return true;
}

function redcap_serve_data() {
    $upload_dir  = wp_upload_dir();
    $output_path = trailingslashit($upload_dir['basedir']) . 'redcap-data.csv';

    if (!file_exists($output_path)) {
        return new WP_REST_Response(['status' => 'error', 'message' => 'No data file found.'], 404);
    }

    $csv = file_get_contents($output_path);
    $response = new WP_REST_Response($csv, 200);
    $response->header('Content-Type', 'text/csv');
    $response->header('Access-Control-Allow-Origin', '*');
    $response->header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    $response->header('Pragma', 'no-cache');
    return $response;
}

function redcap_update(WP_REST_Request $request) {
    $api_url = get_option('redcap_sync_api_url', '');
    $token   = get_option('redcap_sync_token', '');

    if (empty($api_url) || empty($token)) {
        return new WP_REST_Response(['status' => 'error', 'message' => 'Plugin not configured.'], 500);
    }


    $response = wp_remote_post($api_url, array(
        'timeout' => 30,
        'body'    => array(
            'token'               => $token,
            'content'             => 'report',
            'format'              => 'csv',
            'report_id'           => '18198',
            'csvDelimiter'        => '',
            'rawOrLabel'          => 'raw',
            'rawOrLabelHeaders'   => 'raw',
            'exportCheckboxLabel' => 'false',
            'returnFormat'        => 'csv',
        ),
    ));

    if (is_wp_error($response)) {
        return new WP_REST_Response(['status' => 'error', 'message' => $response->get_error_message()], 502);
    }

    $body        = wp_remote_retrieve_body($response);
    $upload_dir  = wp_upload_dir();
    $output_path = trailingslashit($upload_dir['basedir']) . 'redcap-data.csv';

    if (file_put_contents($output_path, $body) === false) {
        return new WP_REST_Response(['status' => 'error', 'message' => 'Could not write file.'], 500);
    }

    // ── Run email-template generation script ────────────────────────────────
    $python_bin   = get_option('redcap_sync_python_bin', 'python3');
    $email_script = get_option('redcap_sync_email_script', '');
    $script_output = '';
    $script_error  = '';

    if (!empty($email_script) && file_exists($email_script)) {
        // Escape arguments to prevent command injection
        $cmd = escapeshellcmd($python_bin) . ' ' . escapeshellarg($email_script)
             . ' ' . escapeshellarg($output_path)
             . ' 2>&1';
        $script_output = shell_exec($cmd);
        if ($script_output === null) {
            $script_error = 'Script execution failed or is disabled on this server.';
        }
    } elseif (!empty($email_script)) {
        $script_error = 'Email script not found: ' . $email_script;
    }

    return new WP_REST_Response([
        'status'        => 'ok',
        'updated'       => gmdate('c'),
        'file'          => $output_path,
        'triggered_by'  => $request->get_param('record') ?? 'manual',
        'preview'       => substr($body, 0, 500),
        'email_script'  => empty($email_script) ? 'not configured' : basename($email_script),
        'script_output' => $script_output,
        'script_error'  => $script_error ?: null,
    ], 200);
}