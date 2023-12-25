import os
import dotenv
import json
import hashlib
import requests
from fireblocks_sdk import FireblocksSDK, TransferPeerPath, VAULT_ACCOUNT, PagedVaultAccountsRequestFilters
from flask import Flask, request, jsonify, render_template

dotenv.load_dotenv()
p2p_api_key = os.getenv('P2P_API_KEY', default='')
cosmos_network = "theta-testnet-001"
#cosmos_network = "cosmoshub-4"
p2p_api_url = f"https://api-test.p2p.org/api/v1/cosmos/{cosmos_network}/staking/"
fireblocks_api_key = '' #e52bff63-d7af-4883-b14a-cd114555e4ae
fireblocks_api_secret = ''
fireblocks_api_base_url = "https://sandbox-api.fireblocks.io"

app = Flask(__name__)


@app.route('/')
def index():
    default_values = {
        "p2p_api_key": '',
        "wallet_address": '',
        "fireblocks_api_key": '',
        "fireblocks_vault_id": "0"
    }
    return render_template('index.html', defaults=default_values)


@app.route('/connect_fireblocks', methods=['POST'])
def connect_fireblocks():
    global fireblocks_api_key
    global fireblocks_api_secret
    fireblocks_api_key = request.form.get('fireblocks_api_key')

    if not fireblocks_api_key:
        return jsonify({"success": False, "error": "No API key provided"})

    try:
        fireblocks_api_secret = open('fireblocks_secret.key', 'r').read()
    except:
        return jsonify({"success": False, "error": "Secret key not found"})

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
            api_key=fireblocks_api_key,
            private_key=fireblocks_api_secret,
            api_base_url=fireblocks_api_base_url
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
        "authorization": "Bearer " + p2p_api_key
    }

    payload = {
        "stashAccountAddress": wallet,
        "amount": amount
    }

    response = requests.post(p2p_api_url + "stake/", headers=headers, json=payload)
    response = response.json()

    if 'error' in response:
        print(json.dumps(response,indent=1))
        return jsonify({'success': False, 'error': response['error'].get('message', 'Unknown error')})

    if 'result' in response and 'transactionData' in response['result']:
        encodedStakingTx = response['result']['transactionData'].get('encodedBody', 'no result')
    else:
        print(json.dumps(response, indent=1))
        return jsonify({'success': False, 'error': 'No tx data in response'})

    StakingTxHash = hashlib.sha256(encodedStakingTx.encode()).hexdigest()
    return jsonify({'success': True, 'tx_data': encodedStakingTx, 'tx_hash': StakingTxHash})


@app.route('/sign_tx', methods=['POST'])
def sign_transaction():

    txHash = request.form.get('txHash', 'no hash')

    fireblocks = FireblocksSDK(
        api_key=fireblocks_api_key,
        private_key=fireblocks_api_secret,
        api_base_url=fireblocks_api_base_url
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
        return jsonify({'success': True, 'result': 'Successfully uploaded'})

    return jsonify({'success': False, 'result': 'An unexpected error occurred'})


app.run(debug=True)
