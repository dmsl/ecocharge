from app import get_all_weather_data

if __name__ == '__main__':
    print("[Cron] Running get_all_weather_data...")
    get_all_weather_data()
    print("[Cron] Finished updating database.")
