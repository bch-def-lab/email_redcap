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
    register_setting('redcap_sync_options', 'redcap_sync_api_url', ['sanitize_callback' => 'esc_url_raw']);
    register_setting('redcap_sync_options', 'redcap_sync_token',   ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('redcap_sync_options', 'redcap_sync_secret',  ['sanitize_callback' => 'sanitize_text_field']);
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
                        placeholder="YOUR_REDCAP_API_TOKEN"
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
    $upload_dir  = wp_upload_dir();
    $output_path = trailingslashit($upload_dir['basedir']) . 'redcap-data.csv';

    // If Vercel already fetched the CSV and forwarded it, use it directly.
    // This avoids a redundant second REDCap API call from the WP side.
    $forwarded_csv = $request->get_param('csv_data');
    if (!empty($forwarded_csv)) {
        if (file_put_contents($output_path, $forwarded_csv) === false) {
            return new WP_REST_Response(['status' => 'error', 'message' => 'Could not write forwarded CSV.'], 500);
        }

        // Purge WP Engine page cache so /data serves fresh content immediately
        if ( function_exists( 'wpe_purge_varnish_cache' ) ) {
            wpe_purge_varnish_cache();
        } elseif ( class_exists( 'WpeCommon' ) ) {
            WpeCommon::purge_varnish_cache();
        }

        return new WP_REST_Response([
            'status'       => 'ok',
            'source'       => 'forwarded',
            'updated'      => gmdate('c'),
            'file'         => $output_path,
            'triggered_by' => $request->get_param('record') ?? 'manual',
        ], 200);
    }

    // No forwarded CSV – fall back to fetching directly from REDCap.
    $api_url = get_option('redcap_sync_api_url', '');
    $token   = get_option('redcap_sync_token', '');

    if (empty($api_url) || empty($token)) {
        return new WP_REST_Response(['status' => 'error', 'message' => 'Plugin not configured.'], 500);
    }

    // Purge WP Engine cache before pulling so stale data is cleared immediately
    if ( function_exists( 'wpe_purge_varnish_cache' ) ) {
        wpe_purge_varnish_cache();
    } elseif ( class_exists( 'WpeCommon' ) ) {
        WpeCommon::purge_varnish_cache();
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

    $body = wp_remote_retrieve_body($response);

    if (file_put_contents($output_path, $body) === false) {
        return new WP_REST_Response(['status' => 'error', 'message' => 'Could not write file.'], 500);
    }

    // Purge WP Engine page cache so /data serves fresh content immediately
    if ( function_exists( 'wpe_purge_varnish_cache' ) ) {
        wpe_purge_varnish_cache();
    } elseif ( class_exists( 'WpeCommon' ) ) {
        WpeCommon::purge_varnish_cache();
    }

    return new WP_REST_Response([
        'status'       => 'ok',
        'source'       => 'self-fetched',
        'updated'      => gmdate('c'),
        'file'         => $output_path,
        'triggered_by' => $request->get_param('record') ?? 'manual',
        'preview'      => substr($body, 0, 500),
    ], 200);
}