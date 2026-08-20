import time
import json
from datetime import datetime
from db import get_db

# Try to import hardware board / ahtx0
try:
    import board
    import adafruit_ahtx0
    HAS_HARDWARE = True
except (ImportError, NotImplementedError):
    HAS_HARDWARE = False

if HAS_HARDWARE:
    class myAHTx0(adafruit_ahtx0.AHTx0):
        @property
        def temperature_humitity(self) -> tuple:
            self._readdata()
            return self._temp, self._humidity

    try:
        i2c = board.I2C()
        sensor = myAHTx0(i2c)
    except Exception as e:
        print(f"Failed to initialize AHTx0 hardware: {e}. Using mock sensor.")
        class MockSensor:
            def __init__(self):
                self.base_temp = 21.5
                self.base_hum = 45.0
            @property
            def temperature_humitity(self) -> tuple:
                import random
                self.base_temp += random.uniform(-0.1, 0.1)
                self.base_hum += random.uniform(-0.2, 0.2)
                self.base_temp = max(18.0, min(26.0, self.base_temp))
                self.base_hum = max(30.0, min(70.0, self.base_hum))
                return self.base_temp, self.base_hum
        sensor = MockSensor()
else:
    class MockSensor:
        def __init__(self):
            self.base_temp = 21.5
            self.base_hum = 45.0
        @property
        def temperature_humitity(self) -> tuple:
            import random
            self.base_temp += random.uniform(-0.1, 0.1)
            self.base_hum += random.uniform(-0.2, 0.2)
            self.base_temp = max(18.0, min(26.0, self.base_temp))
            self.base_hum = max(30.0, min(70.0, self.base_hum))
            return self.base_temp, self.base_hum
    sensor = MockSensor()

avg_amt = 20
meas_delay = 5

temp_tol = .025
hum_tol = 1.
max_time_no_write = 60

def start():
    print("AHTx0 sensor reader started.", flush=True)
    temp_old = 0
    hum_old = 0 
    last_write = time.time()

    while True:
        temp_sum = 0
        hum_sum = 0

        for _ in range(avg_amt):
            t, h = sensor.temperature_humitity
            temp_sum += t
            hum_sum += h

            time.sleep(meas_delay)

        temp = round(temp_sum/avg_amt, 2)
        hum = round(hum_sum/avg_amt, 2)

        now = int(time.time())
        if (
            abs(temp - temp_old) >= temp_tol or 
            abs(hum - hum_old) >= hum_tol or
            now - last_write >= max_time_no_write  
        ):
            last_write = now

            # Write to db
            # We use ISO format for database compatibility with sensor_data table
            time_str = datetime.now().isoformat()
            try:
                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO indoor_sensor_data (time, temperature, humidity) VALUES (?, ?, ?)",
                        (time_str, temp, hum)
                    )
                    conn.commit()
                print(f"Direct AHT sensor: Written to DB -> temp: {temp}, hum: {hum}", flush=True)
            except Exception as e:
                print(f"Direct AHT sensor error writing to DB: {e}", flush=True)
            
        temp_old = temp
        hum_old = hum

if __name__ == "__main__":
    start()
