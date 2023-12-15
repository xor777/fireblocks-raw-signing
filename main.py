import os
import dotenv
import json
import hashlib
import requests
from fireblocks_sdk import FireblocksSDK, TransferPeerPath, VAULT_ACCOUNT
from flask import Flask, request, jsonify, render_template

dotenv.load_dotenv()

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


@app.route('/run_api', methods=['POST'])
def run_p2p():
    # cosmos_network = "theta-testnet-001"
    cosmos_network = "cosmoshub-4"
    p2p_api_url = f"https://api-test.p2p.org/api/v1/cosmos/{cosmos_network}/staking/"
    p2p_api_key = os.getenv("P2P_API_KEY", default="")

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer " + request.form["p2p_api_key"]
    }

    payload = {
        "stashAccountAddress": request.form["stash_wallet_address"],
        "amount": int(request.form["amount"])
    }

    response = requests.post(p2p_api_url + "stake/", headers=headers, json=payload)
    response = response.json()

    print(json.dumps(response, indent=4))

    if 'result' in response and 'transactionData' in response['result']:
        P2PencodedTx = response['result']['transactionData'].get('encodedBody', 'no result')
    else:
        P2PencodedTx = 'no result'

    P2PTxHash = hashlib.sha256(P2PencodedTx.encode()).hexdigest()
    return jsonify({'tx_data': P2PencodedTx, 'tx_hash': P2PTxHash})


@app.route('/launch', methods=['POST'])
def run_fireblocks():

    api_key = request.form.get('fireblocks_api_key','no api key')

    fireblocks_api_key = api_key
    fireblocks_api_base_url = "https://sandbox-api.fireblocks.io"

    txHash = request.form.get('txHash','no hash')

    fireblocks_api_secret = open('fireblocks_secret.key', 'r').read()
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

    status, id = fireblocks.create_transaction(
        tx_type='RAW',
        asset_id='ATOM_COS_TEST',
        source=TransferPeerPath(VAULT_ACCOUNT, "0"),
        extra_parameters=extra
    ).values()

    return jsonify({'fb_result': f'status: {status}, id: {id}'})


@app.route('/upload_fireblocks_secret', methods=['POST'])
def upload_fireblocks_secret():
    if 'fireblocks_secret' not in request.files:
        return jsonify({'error': 'No content'})

    file = request.files['fireblocks_secret']
    if file.filename == '':
        return jsonify({'result': 'No file selected'})

    if file:
        filepath = file.filename
        file.save(filepath)
        return jsonify({'result': 'Successfully uploaded'})

    return jsonify({'result': 'An unexpected error occurred'})


app.run(debug=True)
