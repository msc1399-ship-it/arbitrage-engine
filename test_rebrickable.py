from collectors.rebrickable import RebrickableClient

TEST_SET = "10295-1"

def main():
    client = RebrickableClient()
    data = client.get_set(TEST_SET)

    print("REBRICKABLE API OK")
    print(f"Set: {data.get('set_num')}")
    print(f"Name: {data.get('name')}")
    print(f"Year: {data.get('year')}")
    print(f"Pieces: {data.get('num_parts')}")
    print(f"Theme ID: {data.get('theme_id')}")
    print(f"Image: {data.get('set_img_url')}")

if __name__ == "__main__":
    main()
