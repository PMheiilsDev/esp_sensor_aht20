#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"
#include "esp_err.h"
#include "esp_sleep.h"
#include "esp_attr.h"

#include "nvs_flash.h"

#include "driver/gpio.h"
// #include "driver/adc.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"

#include "driver/i2c_master.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "lwip/netdb.h"


// ============================================================
// Configuration
// ============================================================

#include "wifi_creds.h" // get WIFI_PASSWORD and WIFI_SSID from headerfile 

#define SERVER_IP       "192.168.178.105"
#define SERVER_PORT     5050

// Deep sleep interval
#define SLEEP_TIME_SECONDS              (5*60)
#define SLEEP_TIME_SECONDS_POWER_SAVE   (15*60)
#define MIN_BATTERY_VOLTAGE             3.5f

#define GPIO8_PIN GPIO_NUM_8


// ============================================================
// Battery measurement
// ============================================================

// Battery voltage divider:
//
// Battery ----[R]----+----[R]---- GND
//                    |
//                  GPIO1
//
// Assumed divider ratio = 1/2.
//
// GPIO4 powers/enables the divider.
#define BATTERY_ADC_GPIO       GPIO_NUM_1
#define BATTERY_ENABLE_GPIO    GPIO_NUM_4

#define BATTERY_DIVIDER_RATIO  2.0f

// Don't run AHT20 measurement below this battery voltage.
#define MIN_BATTERY_VOLTAGE    3.5f

// ESP32-C3 ADC1 channel for GPIO1
#define BATTERY_ADC_CHANNEL    ADC_CHANNEL_1

#define ADC_ATTENUATION        ADC_ATTEN_DB_12
#define ADC_BITWIDTH           ADC_BITWIDTH_DEFAULT


// ============================================================
// AHT20
// ============================================================

#define AHT20_VIN_GPIO         GPIO_NUM_9
#define AHT20_GND_GPIO         GPIO_NUM_10

#define AHT20_SCL_GPIO         GPIO_NUM_20
#define AHT20_SDA_GPIO         GPIO_NUM_21

#define AHT20_I2C_ADDRESS      0x38

#define AHT20_COMMAND_TRIGGER  0xAC

#define AHT20_MEASURE_DELAY_MS 100


// ============================================================
// Persistent deep-sleep counter
// ============================================================

RTC_DATA_ATTR uint32_t send_count = 0;


// ============================================================
// Globals
// ============================================================

static const char *TAG = "ESP_SENSOR";

static EventGroupHandle_t wifi_event_group;

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static int retry_count = 0;

#define MAX_WIFI_RETRIES 10


// ============================================================
// Wi-Fi
// ============================================================

static void wifi_event_handler(
    void *arg,
    esp_event_base_t event_base,
    int32_t event_id,
    void *event_data)
{
    if (event_base == WIFI_EVENT &&
        event_id == WIFI_EVENT_STA_START)
    {
        ESP_LOGI(TAG, "Wi-Fi started");

        esp_wifi_connect();
    }

    else if (event_base == WIFI_EVENT &&
             event_id == WIFI_EVENT_STA_DISCONNECTED)
    {
        if (retry_count < MAX_WIFI_RETRIES)
        {
            esp_wifi_connect();
            retry_count++;

            ESP_LOGW(
                TAG,
                "Wi-Fi disconnected, retrying (%d/%d)",
                retry_count,
                MAX_WIFI_RETRIES
            );
        }
        else
        {
            xEventGroupSetBits(
                wifi_event_group,
                WIFI_FAIL_BIT
            );
        }
    }

    else if (event_base == IP_EVENT &&
             event_id == IP_EVENT_STA_GOT_IP)
    {
        ip_event_got_ip_t *event =
            (ip_event_got_ip_t *)event_data;

        ESP_LOGI(
            TAG,
            "Got IP: " IPSTR,
            IP2STR(&event->ip_info.ip)
        );

        retry_count = 0;

        xEventGroupSetBits(
            wifi_event_group,
            WIFI_CONNECTED_BIT
        );
    }
}


static bool wifi_init(void)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(
        esp_netif_init()
    );

    ESP_ERROR_CHECK(
        esp_event_loop_create_default()
    );

    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg =
        WIFI_INIT_CONFIG_DEFAULT();

    ESP_ERROR_CHECK(
        esp_wifi_init(&cfg)
    );

    ESP_ERROR_CHECK(
        esp_event_handler_instance_register(
            WIFI_EVENT,
            ESP_EVENT_ANY_ID,
            &wifi_event_handler,
            NULL,
            NULL
        )
    );

    ESP_ERROR_CHECK(
        esp_event_handler_instance_register(
            IP_EVENT,
            IP_EVENT_STA_GOT_IP,
            &wifi_event_handler,
            NULL,
            NULL
        )
    );

    wifi_config_t wifi_config = {
        .sta = {
            .threshold.authmode = WIFI_AUTH_OPEN,
        },
    };

    strncpy(
        (char *)wifi_config.sta.ssid,
        WIFI_SSID,
        sizeof(wifi_config.sta.ssid)
    );

    strncpy(
        (char *)wifi_config.sta.password,
        WIFI_PASSWORD,
        sizeof(wifi_config.sta.password)
    );

    ESP_ERROR_CHECK(
        esp_wifi_set_mode(WIFI_MODE_STA)
    );

    ESP_ERROR_CHECK(
        esp_wifi_set_config(
            WIFI_IF_STA,
            &wifi_config
        )
    );

    ESP_ERROR_CHECK(
        esp_wifi_start()
    );

    // Disable Wi-Fi power saving.
    // This makes the short send cycle more reliable.
    ESP_ERROR_CHECK(
        esp_wifi_set_ps(WIFI_PS_NONE)
    );

    ESP_LOGI(
        TAG,
        "Connecting to Wi-Fi: %s",
        WIFI_SSID
    );

    EventBits_t bits =
        xEventGroupWaitBits(
            wifi_event_group,
            WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
            pdFALSE,
            pdFALSE,
            pdMS_TO_TICKS(30000)
        );

    if (bits & WIFI_CONNECTED_BIT)
    {
        ESP_LOGI(TAG, "Wi-Fi connected");
        return true;
    }

    ESP_LOGE(TAG, "Failed to connect to Wi-Fi");

    return false;
}


// ============================================================
// Battery ADC
// ============================================================

static bool battery_adc_init(
    adc_oneshot_unit_handle_t *adc_handle,
    adc_cali_handle_t *cal_handle)
{
    adc_oneshot_unit_init_cfg_t init_config = {
        .unit_id = ADC_UNIT_1,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };

    ESP_ERROR_CHECK(
        adc_oneshot_new_unit(
            &init_config,
            adc_handle
        )
    );

    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH,
        .atten = ADC_ATTENUATION,
    };

    ESP_ERROR_CHECK(
        adc_oneshot_config_channel(
            *adc_handle,
            BATTERY_ADC_CHANNEL,
            &config
        )
    );


    // Try ADC calibration.
    *cal_handle = NULL;

#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED

    adc_cali_curve_fitting_config_t cali_config = {
        .unit_id = ADC_UNIT_1,
        .chan = BATTERY_ADC_CHANNEL,
        .atten = ADC_ATTENUATION,
        .bitwidth = ADC_BITWIDTH,
    };

    if (adc_cali_create_scheme_curve_fitting(
            &cali_config,
            cal_handle
        ) == ESP_OK)
    {
        ESP_LOGI(TAG, "ADC calibration enabled");
    }
    else
    {
        ESP_LOGW(TAG, "ADC calibration unavailable");
    }

#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED

    adc_cali_line_fitting_config_t cali_config = {
        .unit_id = ADC_UNIT_1,
        .atten = ADC_ATTENUATION,
        .bitwidth = ADC_BITWIDTH,
    };

    if (adc_cali_create_scheme_line_fitting(
            &cali_config,
            cal_handle
        ) == ESP_OK)
    {
        ESP_LOGI(TAG, "ADC calibration enabled");
    }
    else
    {
        ESP_LOGW(TAG, "ADC calibration unavailable");
    }

#endif

    return true;
}


static float measure_battery_voltage(void)
{
    adc_oneshot_unit_handle_t adc_handle;
    adc_cali_handle_t cal_handle;

    // --------------------------------------------------------
    // Enable voltage divider
    // --------------------------------------------------------

    gpio_set_direction(
        BATTERY_ENABLE_GPIO,
        GPIO_MODE_OUTPUT
    );

    gpio_set_level(
        BATTERY_ENABLE_GPIO,
        1
    );

    // Let divider voltage settle.
    vTaskDelay(
        pdMS_TO_TICKS(10)
    );


    // --------------------------------------------------------
    // Initialize ADC
    // --------------------------------------------------------

    battery_adc_init(
        &adc_handle,
        &cal_handle
    );


    // --------------------------------------------------------
    // Take several readings and average them
    // --------------------------------------------------------

    const int samples = 8;

    int raw_total = 0;

    for (int i = 0; i < samples; i++)
    {
        int raw = 0;

        ESP_ERROR_CHECK(
            adc_oneshot_read(
                adc_handle,
                BATTERY_ADC_CHANNEL,
                &raw
            )
        );

        raw_total += raw;

        vTaskDelay(
            pdMS_TO_TICKS(2)
        );
    }

    int raw_average =
        raw_total / samples;


    // --------------------------------------------------------
    // Convert ADC reading to millivolts
    // --------------------------------------------------------

    int voltage_mv = 0;

    if (cal_handle != NULL)
    {
        ESP_ERROR_CHECK(
            adc_cali_raw_to_voltage(
                cal_handle,
                raw_average,
                &voltage_mv
            )
        );
    }
    else
    {
        // Fallback approximation.
        //
        // This should only be used if calibration isn't
        // available.
        voltage_mv =
            (raw_average * 2500) / 4095;
    }


    float measured_voltage =
        voltage_mv / 1000.0f;

    float battery_voltage =
        measured_voltage *
        BATTERY_DIVIDER_RATIO;


    ESP_LOGI(
        TAG,
        "Battery ADC raw=%d, measured=%.3f V, Vbat=%.3f V",
        raw_average,
        measured_voltage,
        battery_voltage
    );


    // --------------------------------------------------------
    // Disable divider
    // --------------------------------------------------------

    gpio_set_level(
        BATTERY_ENABLE_GPIO,
        0
    );


    // --------------------------------------------------------
    // Clean up ADC
    // --------------------------------------------------------

    if (cal_handle != NULL)
    {
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
        adc_cali_delete_scheme_curve_fitting(
            cal_handle
        );
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
        adc_cali_delete_scheme_line_fitting(
            cal_handle
        );
#endif
    }

    adc_oneshot_del_unit(
        adc_handle
    );


    return battery_voltage;
}


// ============================================================
// AHT20
// ============================================================

static i2c_master_bus_handle_t i2c_bus = NULL;
static i2c_master_dev_handle_t aht20_dev = NULL;


static esp_err_t aht20_init(void)
{
    // --------------------------------------------------------
    // Power sequencing
    //
    // First GND LOW, then VIN HIGH.
    // --------------------------------------------------------

    gpio_set_direction(
        AHT20_GND_GPIO,
        GPIO_MODE_OUTPUT
    );

    gpio_set_level(
        AHT20_GND_GPIO,
        0
    );

    gpio_set_direction(
        AHT20_VIN_GPIO,
        GPIO_MODE_OUTPUT
    );

    gpio_set_level(
        AHT20_VIN_GPIO,
        1
    );

    // Give AHT20 time to power up.
    vTaskDelay(
        pdMS_TO_TICKS(100)
    );


    // --------------------------------------------------------
    // I2C bus
    // --------------------------------------------------------

    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = AHT20_SDA_GPIO,
        .scl_io_num = AHT20_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false,
    };

    esp_err_t err =
        i2c_new_master_bus(
            &bus_config,
            &i2c_bus
        );

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "I2C bus init failed: %s",
            esp_err_to_name(err)
        );

        return err;
    }


    // --------------------------------------------------------
    // AHT20 device
    // --------------------------------------------------------

    i2c_device_config_t dev_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = AHT20_I2C_ADDRESS,
        .scl_speed_hz = 100000,
    };

    err =
        i2c_master_bus_add_device(
            i2c_bus,
            &dev_config,
            &aht20_dev
        );

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "AHT20 device init failed: %s",
            esp_err_to_name(err)
        );

        return err;
    }


    // --------------------------------------------------------
    // Check sensor exists
    // --------------------------------------------------------

    err =
        i2c_master_probe(
            i2c_bus,
            AHT20_I2C_ADDRESS,
            100
        );

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "AHT20 not found at 0x%02X",
            AHT20_I2C_ADDRESS
        );

        return err;
    }

    ESP_LOGI(TAG, "AHT20 detected");

    return ESP_OK;
}


static esp_err_t aht20_read(
    float *temperature,
    float *humidity)
{
    // --------------------------------------------------------
    // Trigger measurement
    // --------------------------------------------------------

    uint8_t command[3] = {
        AHT20_COMMAND_TRIGGER,
        0x33,
        0x00
    };

    esp_err_t err =
        i2c_master_transmit(
            aht20_dev,
            command,
            sizeof(command),
            100
        );

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "AHT20 trigger failed: %s",
            esp_err_to_name(err)
        );

        return err;
    }


    // Wait for measurement.
    vTaskDelay(
        pdMS_TO_TICKS(AHT20_MEASURE_DELAY_MS)
    );


    // --------------------------------------------------------
    // Read 7-byte result
    //
    // byte 0 = status
    // byte 1..5 = measurement
    // byte 6 = CRC
    // --------------------------------------------------------

    uint8_t data[7];

    err =
        i2c_master_receive(
            aht20_dev,
            data,
            sizeof(data),
            100
        );

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "AHT20 read failed: %s",
            esp_err_to_name(err)
        );

        return err;
    }


    // --------------------------------------------------------
    // Check busy bit
    // --------------------------------------------------------

    if (data[0] & 0x80)
    {
        ESP_LOGW(
            TAG,
            "AHT20 still busy"
        );

        return ESP_ERR_TIMEOUT;
    }


    // --------------------------------------------------------
    // Extract 20-bit humidity
    // --------------------------------------------------------

    uint32_t raw_humidity =
        ((uint32_t)data[1] << 12) |
        ((uint32_t)data[2] << 4) |
        ((uint32_t)data[3] >> 4);


    // --------------------------------------------------------
    // Extract 20-bit temperature
    // --------------------------------------------------------

    uint32_t raw_temperature =
        (((uint32_t)data[3] & 0x0F) << 16) |
        ((uint32_t)data[4] << 8) |
        data[5];


    *humidity =
        ((float)raw_humidity * 100.0f)
        / 1048576.0f;

    *temperature =
        ((float)raw_temperature * 200.0f)
        / 1048576.0f
        - 50.0f;


    ESP_LOGI(
        TAG,
        "AHT20: temperature=%.2f C, humidity=%.2f %%",
        *temperature,
        *humidity
    );

    return ESP_OK;
}


static void aht20_power_off(void)
{
    // VIN LOW
    gpio_set_level(
        AHT20_VIN_GPIO,
        0
    );

    // GND stays LOW
    gpio_set_level(
        AHT20_GND_GPIO,
        0
    );


    if (aht20_dev != NULL)
    {
        i2c_master_bus_rm_device(
            aht20_dev
        );

        aht20_dev = NULL;
    }

    if (i2c_bus != NULL)
    {
        i2c_del_master_bus(
            i2c_bus
        );

        i2c_bus = NULL;
    }
}


// ============================================================
// Send JSON to Raspberry Pi
// ============================================================

static bool send_data_to_pi(
    float temperature,
    float humidity,
    float battery_voltage,
    bool power_save_mode)
{
    struct sockaddr_in dest_addr;

    memset(
        &dest_addr,
        0,
        sizeof(dest_addr)
    );

    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port =
        htons(SERVER_PORT);

    if (inet_pton(
            AF_INET,
            SERVER_IP,
            &dest_addr.sin_addr) <= 0)
    {
        ESP_LOGE(
            TAG,
            "Invalid server IP: %s",
            SERVER_IP
        );

        return false;
    }


    ESP_LOGI(
        TAG,
        "Connecting to Pi %s:%d",
        SERVER_IP,
        SERVER_PORT
    );


    int sock =
        socket(
            AF_INET,
            SOCK_STREAM,
            IPPROTO_IP
        );

    if (sock < 0)
    {
        ESP_LOGE(
            TAG,
            "socket() failed: errno=%d",
            errno
        );

        return false;
    }


    int err =
        connect(
            sock,
            (struct sockaddr *)&dest_addr,
            sizeof(dest_addr)
        );

    if (err != 0)
    {
        ESP_LOGE(
            TAG,
            "connect() failed: errno=%d",
            errno
        );

        close(sock);

        return false;
    }


    ESP_LOGI(TAG, "Connected to Pi");


    // --------------------------------------------------------
    // Increment measurement counter
    // --------------------------------------------------------

    send_count++;


    // --------------------------------------------------------
    // Build JSON
    // --------------------------------------------------------

    char message[256];

    snprintf(
        message,
        sizeof(message),
        "{\"count\":%lu,\"temperature\":%.2f,\"humidity\":%.2f,\"vbat\":%.3f,\"power_save\":%s}\n",
        (unsigned long)send_count,
        temperature,
        humidity,
        battery_voltage,
        power_save_mode ? "true" : "false"
    );


    ESP_LOGI(
        TAG,
        "Sending: %s",
        message
    );


    // --------------------------------------------------------
    // Send entire message
    // --------------------------------------------------------

    size_t message_len =
        strlen(message);

    size_t total_sent = 0;

    while (total_sent < message_len)
    {
        int sent =
            send(
                sock,
                message + total_sent,
                message_len - total_sent,
                0
            );

        if (sent < 0)
        {
            ESP_LOGE(
                TAG,
                "send() failed: errno=%d",
                errno
            );

            close(sock);

            return false;
        }

        total_sent += sent;
    }


    ESP_LOGI(
        TAG,
        "Sent %d bytes",
        (int)total_sent
    );


    // --------------------------------------------------------
    // Wait for Pi ACK
    // --------------------------------------------------------

    char ack[16];

    struct timeval timeout = {
        .tv_sec = 5,
        .tv_usec = 0
    };

    setsockopt(
        sock,
        SOL_SOCKET,
        SO_RCVTIMEO,
        &timeout,
        sizeof(timeout)
    );

    int len = recv(
        sock,
        ack,
        sizeof(ack) - 1,
        0
    );

    if (len <= 0)
    {
        ESP_LOGE(
            TAG,
            "Did not receive ACK from Pi"
        );

        close(sock);
        return false;
    }

    ack[len] = '\0';

    ESP_LOGI(
        TAG,
        "Pi ACK: %s",
        ack
    );


    // --------------------------------------------------------
    // Finished
    // --------------------------------------------------------

    shutdown(sock, SHUT_WR);

    close(sock);

    ESP_LOGI(TAG, "Connection closed");

    return true;
}


// ============================================================
// Main
// ============================================================

void app_main(void)
{
    ESP_LOGI(
        TAG,
        "Starting sensor application"
    );

    ESP_LOGI(
        TAG,
        "Measurement count: %lu",
        (unsigned long)send_count
    );

    // GPIO8 LOW immediately after boot/wake
    gpio_reset_pin(GPIO8_PIN);
    gpio_set_direction(GPIO8_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(GPIO8_PIN, 0);


    // --------------------------------------------------------
    // NVS
    // --------------------------------------------------------

    esp_err_t ret =
        nvs_flash_init();

    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(
            nvs_flash_erase()
        );

        ret = nvs_flash_init();
    }

    ESP_ERROR_CHECK(ret);


    // --------------------------------------------------------
    // Battery voltage
    // --------------------------------------------------------

    float battery_voltage =
        measure_battery_voltage();

    bool power_save_mode =
        battery_voltage < MIN_BATTERY_VOLTAGE;

    ESP_LOGI(
        TAG,
        "Battery: %.3f V, power save: %s",
        battery_voltage,
        power_save_mode ? "TRUE" : "FALSE"
    );

    ESP_LOGI(
        TAG,
        "Battery voltage: %.3f V",
        battery_voltage
    );


    // --------------------------------------------------------
    // Only measure AHT20 if battery is high enough
    // --------------------------------------------------------

    float temperature = NAN;
    float humidity = NAN;

    if (battery_voltage >= MIN_BATTERY_VOLTAGE)
    {
        ESP_LOGI(
            TAG,
            "Battery OK (%.3f V >= %.3f V)",
            battery_voltage,
            MIN_BATTERY_VOLTAGE
        );


        if (aht20_init() == ESP_OK)
        {
            if (aht20_read(
                    &temperature,
                    &humidity
                ) != ESP_OK)
            {
                ESP_LOGE(
                    TAG,
                    "AHT20 measurement failed"
                );
            }

            aht20_power_off();
        }
    }
    else
    {
        ESP_LOGW(
            TAG,
            "Battery too low: %.3f V",
            battery_voltage
        );
    }


    // --------------------------------------------------------
    // Wi-Fi
    // --------------------------------------------------------

    if (!wifi_init())
    {
        ESP_LOGE(
            TAG,
            "Wi-Fi connection failed"
        );

        goto sleep;
    }


    // --------------------------------------------------------
    // Send
    // --------------------------------------------------------

    if (isfinite(temperature) &&
        isfinite(humidity))
    {
        send_data_to_pi(
            temperature,
            humidity,
            battery_voltage,
            power_save_mode
        );
    }
    else
    {
        ESP_LOGW(
            TAG,
            "No valid AHT20 measurement, not sending sensor data"
        );
    }


sleep:

    // --------------------------------------------------------
    // Deep sleep
    // --------------------------------------------------------

    uint32_t sleep_time =
        power_save_mode
            ? SLEEP_TIME_SECONDS_POWER_SAVE
            : SLEEP_TIME_SECONDS;

    ESP_LOGI(
        TAG,
        "Going to deep sleep for %lu seconds",
        (unsigned long)sleep_time
    );

    esp_sleep_enable_timer_wakeup(
        (uint64_t)sleep_time * 1000000ULL
    );

    esp_deep_sleep_start();
}