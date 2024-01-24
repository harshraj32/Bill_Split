from flask import Flask, render_template, request, redirect, url_for, make_response,jsonify
from flask_socketio import SocketIO, emit, join_room
import uuid
from bill_splitting import get_merged_df
from werkzeug.utils import secure_filename
import os
app = Flask(__name__ , static_folder='static')
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

sessions = {}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'bill_image' in request.files:
        file = request.files['bill_image']
        filename = secure_filename(file.filename)
                # Ensure the directory exists
        save_directory = 'users/receipts/'
        if not os.path.exists(save_directory):
            os.makedirs(save_directory)

        filepath = os.path.join(save_directory, filename)
        file.save(filepath)

        # Process the image using bill_splitting
        df = get_merged_df(filepath)  # Implement this function in bill_splitting
         # Store table_data in session
        print(df)
        session_id = str(uuid.uuid4())
        #session_password = request.form['session_password']
        items_list = df.to_dict('records')
        sessions[session_id] = {
        "admin": None, 
        "users": {}, 
        "local_users": {},  # New field for local users
        "items": items_list, 
        "splits": {}
        }
        return redirect(url_for('session', session_id=session_id))



@app.route('/start_session', methods=['POST'])
def start_session():
    session_id = str(uuid.uuid4())
    #session_password = request.form['session_password']
    
    df = session.get('table_data', [])
    if not df:
        # Handle case where there is no table data, perhaps redirecting back or showing an error
        return redirect(url_for('home'))
    
    items_list = df.to_dict('records')
    sessions[session_id] = {
    "admin": None, 
    "users": {}, 
    "local_users": {},  # New field for local users
    "items": items_list, 
    "splits": {}
    }
    return redirect(url_for('session', session_id=session_id))

@app.route('/add_local_user/<session_id>', methods=['POST'])
def add_local_user(session_id):
    if session_id in sessions:
        # Check if the current user is the admin
        user_cookie = request.cookies.get('user_session')
        if user_cookie and user_cookie.split('_')[0] == sessions[session_id]["admin"]:
            local_user = request.form.get('local_username')
            if local_user:
                # Initialize local_users if not already done
                if "local_users" not in sessions[session_id]:
                    sessions[session_id]["local_users"] = {}

                # Add the local user
                sessions[session_id]["local_users"][local_user] = [0] * len(sessions[session_id]["items"])

                # Emit an event to update all clients
                socketio.emit('local_user_added', {'session_id': session_id, 'local_user': local_user}, room=session_id)
                
                return "Local user added", 200
            else:
                return "Invalid local user name", 400
        else:
            return "Unauthorized", 403
    else:
        return "Session not found", 404

@app.route('/add_item/<session_id>', methods=['POST'])
def add_item(session_id):
    if session_id in sessions and sessions[session_id]["admin"] == request.cookies.get('user_session').split('_')[0]:
        new_item = {
            "ID": len(sessions[session_id]["items"]) + 1,  # Generate a new ID
            "Name": '',  # Default name
            "Price": 0.0  # Default price
        }
        sessions[session_id]["items"].append(new_item)

        # Update each user's and local user's selection list
        for user in sessions[session_id]["users"]:
            sessions[session_id]["users"][user].append(0)  # Add default selection for new item
        for local_user in sessions[session_id].get("local_users", {}):
            sessions[session_id]["local_users"][local_user].append(0)

        # Emit a socket event to update all clients
        socketio.emit('item_added', {'newItem': new_item}, room=session_id)
        return "Item added", 200
    return "Unauthorized or session not found", 403



@app.route('/get_session_data/<session_id>')
def get_session_data(session_id):
    # Assuming you have a way to retrieve session data by session_id
    session_data = sessions[session_id] # Implement this function
    if session_data:
        return jsonify({
            "users": session_data["users"],
            "items": session_data["items"],
            "splits": session_data["splits"],
            "local_users": session_data.get("local_users", {})  # Default to an empty dict if not present
        })
    else:
        return "Session not found", 404

@app.route('/session/<session_id>')
def session(session_id):
    if session_id in sessions:
        session_data = sessions[session_id]
        splits = calculate_splits(session_id)
        is_admin = False
        user_cookie = request.cookies.get('user_session')
        if user_cookie:
            print(user_cookie)
            username, session_cookie_id = user_cookie.split('_')
            if username == session_data["admin"]:
                is_admin = True
        return render_template('session.html', session_id=session_id, items=session_data["items"], users=session_data["users"], splits=splits, is_admin=is_admin)
    else:
        return "Session not found", 404


def calculate_splits(session_id):
    session_data = sessions[session_id]
    splits = {user: 0 for user in session_data["users"]}  # Initialize splits for regular users
    splits.update({user: 0 for user in session_data["local_users"]})  # Initialize splits for local users

    for i, item in enumerate(session_data["items"]):
        selected_users = [user for user, selections in session_data["users"].items() if selections[i] == 1]
        selected_local_users = [user for user, selections in session_data["local_users"].items() if selections[i] == 1]
        all_selected_users = selected_users + selected_local_users  # Combine both lists
        if all_selected_users:
            cost_per_user = item["Price"] / len(all_selected_users)
            for user in all_selected_users:
                splits[user] += cost_per_user

    return splits


@app.route('/update_item_name', methods=['POST'])
def update_item_name():
    session_id = request.form.get('session_id')
    item_id = int(request.form.get('itemId'))
    new_name = request.form.get('newName')

    if session_id in sessions and sessions[session_id]["admin"] == request.cookies.get('user_session').split('_')[0]:
        for item in sessions[session_id]["items"]:
            if item["ID"] == item_id:
                item["Name"] = new_name
                break
        # Optionally, emit a socket event to update all clients
        socketio.emit('item_updated', {'itemId': item_id, 'newName': new_name}, room=session_id)
        return "Item name updated", 200
    return "Unauthorized or session not found", 403


@app.route('/update_item_price', methods=['POST'])
def update_item_price():
    session_id = request.form.get('session_id')
    item_id = int(request.form.get('itemId'))
    new_price = float(request.form.get('newPrice'))

    if session_id in sessions and sessions[session_id]["admin"] == request.cookies.get('user_session').split('_')[0]:
        for item in sessions[session_id]["items"]:
            if item["ID"] == item_id:
                item["Price"] = new_price
                break
        # Emit an event to update all clients
        socketio.emit('item_price_updated', {'itemId': item_id, 'newPrice': new_price}, room=session_id)
        return "Item price updated", 200
    return "Unauthorized or session not found", 403



@app.route('/join_session/<session_id>', methods=['GET', 'POST'])
def join_session(session_id):
    if session_id in sessions:
        username = request.form['username']
        if sessions[session_id]["admin"] is None:
            sessions[session_id]["admin"] = username
        if request.method == 'POST':
            sessions[session_id]["users"][username] = {}
            sessions[session_id]["users"][username] = [0] * len(sessions[session_id]["items"])
            response = make_response(redirect(url_for('session', session_id=session_id)))
            cookie_value = f"{username}_{session_id}"
            response.set_cookie('user_session', cookie_value)
            return response

        else:
            return render_template('join_session.html', session_id=session_id)
    else:
        return "Session not found", 404


@socketio.on('join')
def on_join(data):
    session_id = data['session_id']
    join_room(session_id)

@app.route('/update_selection/<session_id>', methods=['POST'])
def update_selection(session_id):
    if session_id not in sessions:
        return "Session not found", 404

    username = request.form['username']
    item_index = int(request.form['item_index'])
    is_selected = request.form['is_selected'] == 'true'

    # Check if the user is a local user or a regular user
    if username in sessions[session_id]["users"]:
        # Regular user
        sessions[session_id]["users"][username][item_index] = 1 if is_selected else 0
    elif "local_users" in sessions[session_id] and username in sessions[session_id]["local_users"]:
        # Local user
        sessions[session_id]["local_users"][username][item_index] = 1 if is_selected else 0
    else:
        return "User not found", 404

    # Recalculate splits and emit updates
    sessions[session_id]["splits"] = calculate_splits(session_id)
    socketio.emit('update_data', {
        'splits': calculate_splits(session_id),
        'users': sessions[session_id]["users"],
        'local_users': sessions[session_id]["local_users"],
        'items': sessions[session_id]["items"]
    }, room=session_id)
    
    socketio.emit('selection_updated', {
        'username': username,
        'item_index': item_index,
        'is_selected': is_selected
    }, room=session_id)

    return "Selection updated", 200
    
@app.route('/update_local_user_selection/<session_id>', methods=['POST'])
def update_local_user_selection(session_id):
    if session_id in sessions:
        # Check if the current user is the admin
        user_cookie = request.cookies.get('user_session')
        if user_cookie and user_cookie.split('_')[0] == sessions[session_id]["admin"]:
            username = request.form.get('username')
            item_index = int(request.form.get('item_index'))
            is_selected = request.form.get('is_selected') == 'true'

            # Check if the username exists in local_users
            if 'local_users' in sessions[session_id] and username in sessions[session_id]["local_users"]:
                sessions[session_id]["local_users"][username][item_index] = 1 if is_selected else 0
                print("Inside update local user selection")
                print(session)
                # Emit update to all clients in the session
                socketio.emit('update_data', {
                    'splits': calculate_splits(session_id),
                    'users': sessions[session_id]["users"],
                    'items': sessions[session_id]["items"],
                    'local_users': sessions[session_id]["local_users"]
                }, room=session_id)

                socketio.emit('selection_updated', {
                    'username': username,
                    'item_index': item_index,
                    'is_selected': is_selected
                }, room=session_id)

                return "Local user selection updated", 200
            else:
                return "Local user not found", 404
        else:
            return "Unauthorized", 403
    else:
        return "Session not found", 404



if __name__ == '__main__':
    socketio.run(app, debug=True)
