import os
import dotenv
import json
import hashlib
import requests
import logging
from fireblocks_sdk import (FireblocksSDK, TransferPeerPath, VAULT_ACCOUNT, TRANSACTION_STATUS_COMPLETED,
                            PagedVaultAccountsRequestFilters)
from flask import Flask, request, jsonify, render_template

dotenv.load_dotenv()


class BaseConfig:
    FIREBLOCKS_API_SECRET = ''
    FIREBLOCKS_KEY_FILE = 'fireblocks_secret.key'
    FIREBLOCKS_TRANSACTION_ID = ''


class ProdEnvironment:
    COSMOS_NETWORK = "cosmoshub-4"
    P2P_API_KEY = os.getenv('P2P_API_KEY_PROD')
    P2P_API_URL = f"https://api.p2p.org/api/v1/cosmos/{COSMOS_NETWORK}/"
    FIREBLOCKS_API_BASE_URL = "https://api.fireblocks.io"
    FIREBLOCKS_API_KEY = os.getenv('FIREBLOCKS_API_KEY_PROD')


class TestEnvironment:
    COSMOS_NETWORK = "theta-testnet-001"
    P2P_API_KEY = os.getenv('P2P_API_KEY_TEST')
    P2P_API_URL = f"https://api-test.p2p.org/api/v1/cosmos/{COSMOS_NETWORK}/"
    FIREBLOCKS_API_BASE_URL = "https://sandbox-api.fireblocks.io"
    FIREBLOCKS_API_KEY = os.getenv('FIREBLOCKS_API_KEY_TEST')


def get_fireblocks_sdk():
    fireblocks_api_key = app.config['FIREBLOCKS_API_KEY']
    fireblocks_api_secret = app.config['FIREBLOCKS_API_SECRET']
    fireblocks_api_base_url = app.config['FIREBLOCKS_API_BASE_URL']

    return FireblocksSDK(
        api_key=fireblocks_api_key,
        private_key=fireblocks_api_secret,
        api_base_url=fireblocks_api_base_url
    )


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

app = Flask(__name__)


def set_environment(environment):
    app.config.from_object(BaseConfig)
    if environment == 'prod':
        app.config.from_object(ProdEnvironment)
    else:
        app.config.from_object(TestEnvironment)


@app.route('/')
def index():
    default_values = {
        "wallet_address": '',
        "fireblocks_api_key": app.config['FIREBLOCKS_API_KEY'],
        "fireblocks_vault_id": "0"
    }
    return render_template('index.html', defaults=default_values)


@app.route('/connect_fireblocks', methods=['POST'])
def connect_fireblocks():
    fireblocks_api_key = request.form.get('fireblocks_api_key')

    if not fireblocks_api_key:
        return jsonify({"success": False, "error": "No API key provided"})

    try:
        fireblocks_api_secret = open(app.config['FIREBLOCKS_KEY_FILE'], 'r').read()
    except Exception as e:
        return jsonify({"success": False, "error": "Secret key not found: "+str(e)})

    app.config['FIREBLOCKS_API_KEY'] = fireblocks_api_key
    app.config['FIREBLOCKS_API_SECRET'] = fireblocks_api_secret
    fireblocks = get_fireblocks_sdk()

    try:
        vaults = fireblocks.get_vault_accounts_with_page_info(PagedVaultAccountsRequestFilters())
        app.logger.debug(vaults)
    except Exception as e:
        return jsonify({"success": False, "error": "Error getting vaults: " + str(e)})

    return jsonify({'success': True, 'vaults': vaults})


@app.route('/upload_fireblocks_secret', methods=['POST'])
def upload_fireblocks_secret():
    if 'fireblocks_secret' not in request.files:
        return jsonify({'success': False, 'result': 'Choose file to upload'})

    file = request.files['fireblocks_secret']
    if file.filename == '':
        return jsonify({'success': False, 'result': 'No file selected'})

    if file:
        filepath = file.filename
        file.save(filepath)
        app.config['FIREBLOCKS_KEY_FILE'] = file.filename
        app.logger.debug(f'Key file name: {file.filename}')
        return jsonify({'success': True, 'result': 'Successfully uploaded'})

    return jsonify({'success': False, 'result': 'An unexpected error occurred'})


@app.route('/get_wallet_address', methods=['POST'])
def get_wallet_address():
    data = request.get_json(force=True)

    vault_account_id = data.get('vault_account_id')
    asset_id = data.get('asset_id')

    try:
        fireblocks = get_fireblocks_sdk()
        addr = fireblocks.get_deposit_addresses(vault_account_id=vault_account_id, asset_id=asset_id)
        app.logger.debug(json.dumps(addr, indent=1))

        pub_key = fireblocks.get_public_key_info_for_vault_account(
            asset_id=asset_id,
            vault_account_id=vault_account_id,
            compressed=True,
            change=0,
            address_index=0)
        app.logger.debug(json.dumps(pub_key, indent=1))
        pub_key = pub_key["publicKey"]

        return jsonify({'success': True, 'address': addr[0]['address'], 'pub_key': pub_key})
    except Exception as e:
        return jsonify({'success': False, 'error': 'Error calling Fireblocks API: ' + str(e)})


@app.route('/create_tx', methods=['POST'])
def create_staking_tx():
    data = request.get_json(force=True)

    amount = data.get("amount", "0")
    amount = float(amount) if amount.replace('.', '', 1).isdigit() else 0.0
    wallet = data.get("stash_wallet_address", "").strip()

    if not wallet or amount == 0:
        return jsonify({'success': False, 'error': 'No wallet specified or amount = 0'})

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer " + app.config['P2P_API_KEY']
    }

    payload = {
        "stashAccountAddress": wallet,
        "amount": amount
    }

    app.logger.debug(json.dumps(payload, indent=1))
    response = requests.post(app.config['P2P_API_URL'] + "staking/stake/", headers=headers, json=payload)
    response = response.json()
    app.logger.debug(json.dumps(response, indent=1))

    if 'error' in response and response['error'] is not None:
        return jsonify({'success': False, 'error': response['error'].get('message', 'Unknown error')})

    encoded_body = response['result']['transactionData'].get('encodedBody', 'no result')
    encoded_auth_info = response['result']['transactionData'].get('encodedAuthInfo', 'no result')
    message_hash = hashlib.sha256(encoded_body.encode()).hexdigest()

    return jsonify({'success': True,
                    'encodedBody': encoded_body,
                    'encodedAuthInfo': encoded_auth_info,
                    'messageHash': message_hash})


@app.route('/send_tx', methods=['POST'])
def send_transaction():
    data = request.get_json(force=True)

    message_hash = data.get('message_hash', None)
    if message_hash is None:
        return jsonify({'success': False, 'error': 'No tx hash provided'})

    fireblocks = get_fireblocks_sdk()

    extra = {
        "rawMessageData": {
            "messages": [
                {
                    "content": message_hash,
                }
            ]
        }
    }

    tx_id, status = fireblocks.create_transaction(
        tx_type='RAW',
        asset_id='ATOM_COS_TEST',
        source=TransferPeerPath(VAULT_ACCOUNT, "0"),
        extra_parameters=extra
    ).values()

    return jsonify({'success': True, 'txId': tx_id, 'txStatus': status})


@app.route('/check_tx_status', methods=['POST'])
def check_tx_status():
    data = request.get_json(force=True)
    tx_id = data.get('transaction_id', '')

    if not tx_id:
        return jsonify({'success': False, 'error': 'No transaction ID provided'})

    # 39d0cabd-0029-4f9c-b7c9-b7042c8f5051
    fireblocks = FireblocksSDK(
        api_key=app.config['FIREBLOCKS_API_KEY'],
        private_key=app.config['FIREBLOCKS_API_SECRET'],
        api_base_url=app.config['FIREBLOCKS_API_BASE_URL']
    )

    try:
        tx_info = fireblocks.get_transaction_by_id(tx_id)
        app.logger.debug(json.dumps(tx_info, indent=1))
        status = tx_info.get('status', 'unknown')
        full_sig = 'none'
        if status == TRANSACTION_STATUS_COMPLETED:
            full_sig = tx_info['signedMessages'][0]['signature']['fullSig']
        return jsonify({'success': True, 'status': status, 'fullSig': full_sig})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/encode_tx', methods=['POST'])
def encode_tx():
    data = request.get_json(force=True)
    delegator_address = data['delegator_address']
    encoded_body = data.get('encoded_body', '')
    encoded_auth_info = data.get('encoded_auth_info', '')
    signature = data.get('signature', '')

    if not encoded_body or not encoded_auth_info or not signature:
        return jsonify({'success': False, 'error': 'No transaction stuff provided (enc body, auth info, signature)'})

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer " + app.config['P2P_API_KEY']
    }

    payload = {
        "delegatorAddress": delegator_address,
        "encodedBody": encoded_body,
        "encodedAuthInfo": encoded_auth_info,
        "signature": signature
    }

    app.logger.debug(json.dumps(payload, indent=1))

    response = requests.post(app.config['P2P_API_URL'] + "transaction/encode/", headers=headers, json=payload)
    response = response.json()

    app.logger.debug(json.dumps(response, indent=1))

    if 'error' in response and response['error'] is not None:
        return jsonify({'success': False, 'error': response['error'].get('message', 'Unknown error')})

    return jsonify({'success': True, 'encodedTx': 'enc tx'})


@app.route('/broadcast_tx', methods=['POST'])
def broadcast_tx():
    data = request.get_json(force=True)
    encoded_tx = data.get('encoded_tx', '')

    if not encoded_tx:
        return jsonify({'success': False, 'error': 'No transaction data provided'})

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer " + app.config['P2P_API_KEY']
    }

    payload = {
        "signedTransaction": encoded_tx
    }

    app.logger.debug(json.dumps(payload, indent=1))
    response = requests.post(app.config['P2P_API_URL'] + "transaction/send/", headers=headers, json=payload)
    response = response.json()
    app.logger.debug(json.dumps(response, indent=1))

    if 'error' in response and response['error'] is not None:
        return jsonify({'success': False, 'error': response['error'].get('message', 'Unknown error')})

    return jsonify({'success': True, 'result': 'done'})


if __name__ == '__main__':
    environment = os.getenv('APPLICATION_ENVIRONMENT', 'test')
    set_environment('test')
    logging.info(f'Environment: {environment}')
    app.run(host='0.0.0.0', port=8000, debug=False if environment == 'test' else False)
