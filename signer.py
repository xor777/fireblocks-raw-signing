import os
import dotenv
import json
import hashlib
import requests
import logging
from fireblocks_sdk import FireblocksSDK, TransferPeerPath, VAULT_ACCOUNT, PagedVaultAccountsRequestFilters
from flask import Flask, request, jsonify, render_template

dotenv.load_dotenv()

class BaseConfig:
    FIREBLOCKS_API_SECRET = ''
    FIREBLOCKS_KEY_FILE = 'fireblocks_secret.key'

class ProdEnvironment:
    COSMOS_NETWORK = "cosmoshub-4"
    P2P_API_KEY = os.getenv('P2P_API_KEY_PROD')
    P2P_API_URL = f"https://api.p2p.org/api/v1/cosmos/{COSMOS_NETWORK}/staking/"
    FIREBLOCKS_API_BASE_URL = "https://api.fireblocks.io"
    FIREBLOCKS_API_KEY = os.getenv('FIREBLOCKS_API_KEY_PROD')

class TestEnvironment:
    COSMOS_NETWORK = "theta-testnet-001"
    P2P_API_KEY = os.getenv('P2P_API_KEY_TEST')
    P2P_API_URL = f"https://api-test.p2p.org/api/v1/cosmos/{COSMOS_NETWORK}/staking/"
    FIREBLOCKS_API_BASE_URL = "https://sandbox-api.fireblocks.io"
    FIREBLOCKS_API_KEY = os.getenv('FIREBLOCKS_API_KEY_TEST')

logging.basicConfig(level = logging.DEBUG,
                    format = '%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

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

@app.route('/switch_environment', methods=['POST'])
def switch_environment():
    # nothing here yet
    return

@app.route('/connect_fireblocks', methods=['POST'])
def connect_fireblocks():
    fireblocks_api_key = request.form.get('fireblocks_api_key')

    if not fireblocks_api_key:
        return jsonify({"success": False, "error": "No API key provided"})

    try:
        fireblocks_api_secret = open(app.config['FIREBLOCKS_KEY_FILE'], 'r').read()
    except:
        return jsonify({"success": False, "error": "Secret key not found"})

    app.config['FIREBLOCKS_API_KEY'] = fireblocks_api_key
    app.config['FIREBLOCKS_API_SECRET'] = fireblocks_api_secret
    fireblocks_api_base_url = app.config['FIREBLOCKS_API_BASE_URL']

    fireblocks = FireblocksSDK(
        api_key=fireblocks_api_key,
        private_key=fireblocks_api_secret,
        api_base_url=fireblocks_api_base_url
    )

    try:
        vaults = fireblocks.get_vault_accounts_with_page_info(PagedVaultAccountsRequestFilters())
    except Exception as e:
        return jsonify({"success": False, "error": "Error getting vaults: " + str(e)})

    return jsonify({'success': True, 'vaults': vaults})

@app.route('/get_wallet_address', methods=['POST'])
def get_wallet_address():
    data = request.get_json(force=True)

    vault_account_id = data.get('vault_account_id')
    asset_id = data.get('asset_id')

    try:
        fireblocks = FireblocksSDK(
            api_key=app.config['FIREBLOCKS_API_KEY'],
            private_key=app.config['FIREBLOCKS_API_SECRET'],
            api_base_url=app.config['FIREBLOCKS_API_BASE_URL']
        )

        addr = fireblocks.get_deposit_addresses(vault_account_id=vault_account_id, asset_id=asset_id)
        return jsonify({'success': True, 'address': addr[0]['address']})

    except Exception as e:
        return jsonify({'success': False, 'error': 'Error calling Fireblocks API: ' + str(e)})


@app.route('/create_tx', methods=['POST'])
def create_staking_tx():
    amount = request.form.get("amount", "0")
    amount = int(amount) if amount.isdigit() else 0
    wallet = request.form.get("stash_wallet_address", "").strip()

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

    response = requests.post(app.config['P2P_API_URL'] + "stake/", headers=headers, json=payload)
    response = response.json()

    if 'error' in response:

        app.logger.error(json.dumps(response,indent=1))
        return jsonify({'success': False, 'error': response['error'].get('message', 'Unknown error')})

    if 'result' in response and 'transactionData' in response['result']:
        encodedStakingTx = response['result']['transactionData'].get('encodedBody', 'no result')
    else:
        app.logger.error(json.dumps(response, indent=1))
        return jsonify({'success': False, 'error': 'No tx data in response'})

    StakingTxHash = hashlib.sha256(encodedStakingTx.encode()).hexdigest()
    return jsonify({'success': True, 'tx_data': encodedStakingTx, 'tx_hash': StakingTxHash})


@app.route('/sign_tx', methods=['POST'])
def sign_transaction():

    txHash = request.form.get('txHash', 'no hash')

    fireblocks = FireblocksSDK(
        api_key=app.config['FIREBLOCKS_API_KEY'],
        private_key=app.config['FIREBLOCKS_API_SECRET'],
        api_base_url=app.config['FIREBLOCKS_API_BASE_URL']
    )

    extra = {
        "rawMessageData": {
            "messages": [
                {
                    "content": txHash,
                }
            ]
        }
    }

    txId, status = fireblocks.create_transaction(
        tx_type='RAW',
        asset_id='ATOM_COS_TEST',
        source=TransferPeerPath(VAULT_ACCOUNT, "0"),
        extra_parameters=extra
    ).values()

    return jsonify({'fb_result': f'status: {status}, id: {txId}'})


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

if __name__ == '__main__':
    set_environment('test')
    app.run(debug=True)
