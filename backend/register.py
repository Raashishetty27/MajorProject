from fastapi import FastAPI, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import face_recognition
import numpy as np
import io, hashlib
from web3 import Web3

app = FastAPI()

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database & table
conn = sqlite3.connect("voters.db")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS voters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    address TEXT,
    dob TEXT,
    voter_id TEXT UNIQUE,
    face_encoding BLOB
)''')
conn.commit()
conn.close()

# ---------------- Blockchain Setup ----------------
w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))  # Ganache/Hardhat/Local RPC
account = w3.eth.accounts[0]  # change if needed
private_key = "YOUR_PRIVATE_KEY"  # replace with real key for deployment

# Load deployed contract
contract_address = "0xYourContractAddressHere"  # replace after deployment
contract_abi = [
    {
        "inputs": [
            {"internalType": "string", "name": "_voterId", "type": "string"},
            {"internalType": "string", "name": "_hash", "type": "string"}
        ],
        "name": "registerVoter",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
contract = w3.eth.contract(address=contract_address, abi=contract_abi)


# ---------------- API Routes ----------------
@app.post("/register")
async def register_voter(
    name: str = Form(...),
    address: str = Form(...),
    dob: str = Form(...),
    voterId: str = Form(...),
    faceScan: UploadFile = File(...)
):
    # Read uploaded image
    image_bytes = await faceScan.read()
    image = face_recognition.load_image_file(io.BytesIO(image_bytes))
    boxes = face_recognition.face_locations(image)

    if not boxes:
        return {"status": "error", "message": "No face detected"}

    # Get face encoding
    encoding = face_recognition.face_encodings(image, boxes)[0]
    encoding_bytes = np.array(encoding).tobytes()

    try:
        # Save voter in SQLite
        conn = sqlite3.connect("voters.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO voters (name, address, dob, voter_id, face_encoding) VALUES (?, ?, ?, ?, ?)",
            (name, address, dob, voterId, encoding_bytes)
        )
        conn.commit()
        conn.close()

        # Compute SHA256 hash of voter record
        record = f"{name}{address}{dob}{voterId}".encode()
        record_hash = hashlib.sha256(record).hexdigest()

        # Send hash to blockchain
        txn = contract.functions.registerVoter(voterId, record_hash).build_transaction({
            "from": account,
            "gas": 2000000,
            "nonce": w3.eth.get_transaction_count(account),
        })

        signed_txn = w3.eth.account.sign_transaction(txn, private_key=private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        return {
            "status": "success",
            "message": "Voter registered successfully (SQLite + Blockchain)",
            "tx_hash": receipt.transactionHash.hex()
        }

    except sqlite3.IntegrityError:
        return {"status": "error", "message": "Voter ID already registered"}
