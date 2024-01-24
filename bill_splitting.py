import json
import pandas as pd
import numpy as np
import re
import http.client
import json
from PIL import Image, ImageEnhance
import os
import cv2 
from supabase import create_client, Client
import time

def cv2_enhance_contrast(img, factor):
    mean = np.uint8(cv2.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))[0])
    img_deg = np.ones_like(img) * mean
    return cv2.addWeighted(img, factor, img_deg, 1-factor, 0.0)



def enhance_contrast(image_path):
    #print("image path check:", image_path)
    original_image = Image.open(image_path,mode='r', formats=None)
    
        # Enhance the contrast
    #enhancer = ImageEnhance.Contrast(image_path).enhance(2.0)
    #high_contrast_img = enhancer.enhance(2.0)  # The factor 2.0 increases the contrast
    #high_contrast_img = cv2_enhance_contrast(image_path, 2.0)
    return 'high'
    


def upload_file_to_veryfi(file_url):
    conn = http.client.HTTPSConnection("api.veryfi.com")

    payload = json.dumps({
      "file_url": file_url
    })

    headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json',
  'CLIENT-ID': 'vrfAcYwgyn0fWe90beToVzLOFrXsWepYu1KI1nB',
  'AUTHORIZATION': 'apikey harshraj101999:a8136c087f2919a8dbbdb4795558e889'

    }

    conn.request("POST", "/api/v8/partner/documents", payload, headers)
    res = conn.getresponse()
    data = res.read()

    conn.close()

    return json.loads(data.decode("utf-8"))

def get_processed_document(document_id):
    conn = http.client.HTTPSConnection("api.veryfi.com")
    payload = ''
    headers = {
  'Accept': 'application/json',
  'CLIENT-ID': 'vrfAcYwgyn0fWe90beToVzLOFrXsWepYu1KI1nB',
  'AUTHORIZATION': 'apikey harshraj101999:a8136c087f2919a8dbbdb4795558e889'

    }

    conn.request("GET", f"/api/v8/partner/documents/{document_id}", payload, headers)
    res = conn.getresponse()
    data = res.read()

    conn.close()

    return json.loads(data.decode("utf-8"))

def upload_file_to_supabase(filepath: str, bucket_name: str, folder_name: str, supabase_url: str, supabase_key: str) -> str:
    # Create a Supabase client
    supabase: Client = create_client(supabase_url, supabase_key)
    file_name = filepath.split('/')[-1]

    # Construct the full path on storage
    full_path_on_storage = f"{folder_name}/{file_name}"
    
    print("Current working directory:", os.getcwd())
    # Upload the file
    # Check if the file already exists in the storage
    
        # Upload the file
    try:
        # Attempt to upload the file
        with open(filepath, 'rb') as f:
            response = supabase.storage.from_(bucket_name).upload(
                path=full_path_on_storage,
                file=f,
                file_options={"content-type": "image/jpeg"}
            )

        if response.status_code != 200:
            raise Exception(f"Failed to upload file: {response.text}")

        print("File uploaded successfully.")

    except Exception as e:
        # Check if the exception message contains 'Duplicate'
        if 'Duplicate' in str(e):
            print("File already exists. Skipping upload.")
        else:
            # If the error is not due to a duplicate, re-raise the exception
            raise
    # Construct the public file URL
    file_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{full_path_on_storage}"
    return file_url

def process_and_upload_image(filepath, bucket_name, folder_name, supabase_url, supabase_key):
    # Enhance the image
    #enhanced_image = enhance_contrast(filepath)
    
    # Modify the file path for the enhanced image
    #base, ext = os.path.splitext(filepath)
    #temp_path = f"{base}_enhanced{ext}"

    # Save the enhanced image
    #enhanced_image.save(temp_path)

    # Upload the enhanced image
    file_url = upload_file_to_supabase(filepath, bucket_name, folder_name, supabase_url, supabase_key)

    # Optionally, remove the temp file if no longer needed
    os.remove(filepath)

    return file_url



def preprocess_text_fields(data):
    text_fields = [item['text'] for item in data['line_items']]
    return [line[2:] if line.startswith(('F ', 'E ')) else line for line in text_fields]

def extract_data_from_text(text_fields):
    pattern = r"(\d+)\s+(.*?)\t(\d+\.\d+)(\s+[AT])?"
    data_list = []
    for text in text_fields:
        match = re.search(pattern, text)
        if match:
            item_id = match.group(1)
            item_name = match.group(2)
            item_price = float(match.group(3))
            tax_status = match.group(4).strip() if match.group(4) else 'No tax'
            data_list.append((item_id, item_name, item_price, tax_status))
    return pd.DataFrame(data_list, columns=['ID', 'Name', 'Price', 'Tax Status'])

def is_id_match(id1, id2, allowance=2):
    max_length = max(len(id1), len(id2))
    padded_id1 = id1.zfill(max_length)
    padded_id2 = id2.zfill(max_length)
    mismatches = sum(1 for a, b in zip(padded_id1, padded_id2) if a != b)
    return mismatches <= allowance

def process_discounts(df):
    pattern = r'/(\s*\d+\s*\d*)'
    discounted_prices = []
    indices_to_drop = []
    for i in range(1, len(df)):
        match = re.search(pattern, df.loc[i, 'Name'])
        if match:
            extracted_id = match.group(1).replace(' ', '0').lstrip('0')
            previous_id = df.loc[i-1, 'ID'].lstrip('0')
            if is_id_match(extracted_id, previous_id):
                discounted_prices.append({'ID': df.loc[i-1, 'ID'], 'Discount Amount': df.loc[i, 'Price']})
                indices_to_drop.append(i)
    discount_df = pd.DataFrame(discounted_prices).drop_duplicates()
    return df.drop(indices_to_drop), discount_df

def merge_and_calculate_prices(df, discount_df):
    df['ID'] = df['ID'].astype(str)
    discount_df['ID'] = discount_df['ID'].astype(str)
    df_merged = pd.merge(df, discount_df, on='ID', how='left')
    df_merged['Discount Amount'] = df_merged['Discount Amount'].fillna(0)
    df_merged['Discounted Price'] = df_merged['Price'] - df_merged['Discount Amount']
    tax_percentage = 9.125 / 100
    df_merged['Tax'] = df_merged.apply(lambda row: row['Discounted Price'] * tax_percentage if row['Tax Status'] == 'A' else 0, axis=1)
    df_merged['Final Price'] = df_merged['Discounted Price'] + df_merged['Tax']
    return df_merged

def calculate_totals(df_merged):
    sub_total = df_merged['Discounted Price'].sum()
    tax_total = df_merged['Tax'].sum()
    total_price = df_merged['Final Price'].sum()
    return sub_total, tax_total, total_price

def get_merged_df(user_file_path):
    # file_path = 'bill_split_1.JSON'

    # SUPABASE_URL = 'https://lesrfpiwruzymhfajaex.supabase.co'
    # SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxlc3JmcGl3cnV6eW1oZmFqYWV4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3MDMzNzU1MjYsImV4cCI6MjAxODk1MTUyNn0.0IrkR16j2R9nyf8rvo0Xv__UbX9kxW73rjSt7RD2u0g'
    # BUCKET_NAME = 'buck'
    # #user_file_path = '/content/drive/Shareddrives/Bill_Split_Datasets/test_image_bill.jpeg'
    # # Path where the file will be stored in Supabase storage
    # folder_name = 'bill_receipts'
    # #user_image = enhance_contrast(user_file_path)
    # # Upload the file
    # uploaded_file_url = process_and_upload_image(user_file_path, BUCKET_NAME, folder_name, SUPABASE_URL, SUPABASE_KEY)
    # '''print(f"Uploaded file URL: {uploaded_file_url}")'''
    # response = upload_file_to_veryfi(uploaded_file_url)
    # #print(response)
    # document_id = response['id']  # Assuming the response contains an 'id'
    # # Retrieve processed document
    # processed_data = get_processed_document(document_id)
    # text_fields = preprocess_text_fields(processed_data)
    # df = extract_data_from_text(text_fields)
    # df, discount_df = process_discounts(df)
    # df_merged = merge_and_calculate_prices(df, discount_df)
    # sub_total, tax_total, total_price = calculate_totals(df_merged)
    data = {
    "ID": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "Name": ["Apples", "Bread", "Milk", "Eggs", "Cheese", "Tomatoes", "Bananas", "Oranges", "Chicken", "Fish"],
    "Price": [2.5, 3.0, 1.75, 2.2, 3.5, 1.2, 0.5, 1.5, 5.0, 6.0],
    "Final Price": [2.0, 2.5, 1.5, 2.0, 3.0, 1.0, 0.4, 1.3, 4.5, 5.5]
}
    
    data2 = {
    "ID": [1],
    "Name": ["None"],
    "Price": [0],
    "Final Price": [0]
    }

    return pd.DataFrame(data2)
    '''print("Sub Total:", sub_total)
    print("Tax Total:", tax_total)
    print("Total Price:", total_price)'''
    return df_merged
    

if __name__ == "__main__":
    get_merged_df('users/receipts/example.jpeg')
