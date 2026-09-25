"""Green/red LEDs and a buzzer on the Raspberry Pi GPIO.
On a laptop (no gpiozero or no GPIO chip) it quietly does nothing, so the same
code runs on both machines."""

import threading

from . import config


class GPIOFeedback:
    def __init__(self, enabled=config.GPIO_ENABLED):
        self.available = False
        if not enabled:
            return
        try:
            from gpiozero import LED, Buzzer
            self.green = LED(config.GREEN_LED_PIN)
            self.red = LED(config.RED_LED_PIN)
            self.buzzer = Buzzer(config.BUZZER_PIN)
            self.available = True
            print("[GPIO] LEDs and buzzer ready")
        except Exception as exc:  # not a Pi, or pins unavailable
            print(f"[GPIO] Hardware feedback disabled ({exc.__class__.__name__})")

    def show_form(self, form_ok):
        if not self.available:
            return
        if form_ok:
            self.green.on()
            self.red.off()
        else:
            self.green.off()
            self.red.on()

    def beep(self, seconds=config.BUZZER_BEEP_SECONDS):
        if not self.available:
            return
        self.buzzer.on()
        threading.Timer(seconds, self.buzzer.off).start()

    def off(self):
        if not self.available:
            return
        self.green.off()
        self.red.off()
        self.buzzer.off()
