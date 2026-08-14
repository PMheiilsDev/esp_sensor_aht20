#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

#include "esp_log.h"
#include "esp_err.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "lwip/netdb.h"


// ============================================================
// Configuration
// ============================================================

#include "wifi_creds.h" // get WIFI_PASSWORD and WIFI_SSID from headerfile 

#define SERVER_IP       "192.168.178.105"
#define SERVER_PORT     5050

#define SEND_INTERVAL_MS 5000


// ============================================================
// Constants
// ============================================================

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static const char *TAG = "ESP_SENSOR";

static EventGroupHandle_t wifi_event_group;

static int retry_count = 0;

#define MAX_WIFI_RETRIES 10


// ============================================================
// Wi-Fi event handler
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


// ============================================================
// Wi-Fi initialization
// ============================================================

static void wifi_init(void)
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

    ESP_LOGI(TAG, "Connecting to Wi-Fi: %s", WIFI_SSID);

    EventBits_t bits = xEventGroupWaitBits(
        wifi_event_group,
        WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE,
        pdFALSE,
        portMAX_DELAY
    );

    if (bits & WIFI_CONNECTED_BIT)
    {
        ESP_LOGI(TAG, "Wi-Fi connected");
    }
    else if (bits & WIFI_FAIL_BIT)
    {
        ESP_LOGE(TAG, "Failed to connect to Wi-Fi");
    }
}


// ============================================================
// Send data to Raspberry Pi
// ============================================================

static void send_data_to_pi(void)
{
    ESP_LOGI(
        TAG,
        "Connecting to Pi %s:%d",
        SERVER_IP,
        SERVER_PORT
    );

    struct sockaddr_in dest_addr;

    memset(
        &dest_addr,
        0,
        sizeof(dest_addr)
    );

    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(SERVER_PORT);

    int result = inet_pton(
        AF_INET,
        SERVER_IP,
        &dest_addr.sin_addr
    );

    if (result <= 0)
    {
        ESP_LOGE(
            TAG,
            "Invalid server IP address: %s",
            SERVER_IP
        );

        return;
    }

    int sock = socket(
        AF_INET,
        SOCK_STREAM,
        IPPROTO_IP
    );

    if (sock < 0)
    {
        ESP_LOGE(
            TAG,
            "Unable to create socket: errno %d",
            errno
        );

        return;
    }

    int err = connect(
        sock,
        (struct sockaddr *)&dest_addr,
        sizeof(dest_addr)
    );

    if (err != 0)
    {
        ESP_LOGE(
            TAG,
            "Socket connection failed: errno %d",
            errno
        );

        close(sock);

        return;
    }

    ESP_LOGI(TAG, "Connected to Pi");


    // --------------------------------------------------------
    // This is the data we are sending.
    // Later we can replace this with sensor data.
    // --------------------------------------------------------

    const char *message =
        "hello from esp32-c3";


    int sent = send(
        sock,
        message,
        strlen(message),
        0
    );

    if (sent < 0)
    {
        ESP_LOGE(
            TAG,
            "Failed to send data: errno %d",
            errno
        );
    }
    else
    {
        ESP_LOGI(
            TAG,
            "Sent: %s",
            message
        );
    }


    // --------------------------------------------------------
    // Close connection
    // --------------------------------------------------------

    shutdown(
        sock,
        SHUT_RDWR
    );

    close(sock);

    ESP_LOGI(TAG, "Connection closed");
}


// ============================================================
// Main application
// ============================================================

void app_main(void)
{
    ESP_LOGI(
        TAG,
        "Starting ESP32 sensor application"
    );


    // --------------------------------------------------------
    // Initialize NVS
    // --------------------------------------------------------

    esp_err_t ret = nvs_flash_init();

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
    // Connect to Wi-Fi
    // --------------------------------------------------------

    wifi_init();


    // --------------------------------------------------------
    // Main loop
    // --------------------------------------------------------

    while (1)
    {
        EventBits_t bits =
            xEventGroupGetBits(
                wifi_event_group
            );

        if (bits & WIFI_CONNECTED_BIT)
        {
            send_data_to_pi();
        }
        else
        {
            ESP_LOGW(
                TAG,
                "Wi-Fi is not connected"
            );
        }

        vTaskDelay(
            pdMS_TO_TICKS(SEND_INTERVAL_MS)
        );
    }
}