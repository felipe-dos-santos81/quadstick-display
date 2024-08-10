#!/usr/bin/env bash

if ! grep -q Raspberry /proc/cpuinfo; then
  echo "This script is intended to run on a Raspberry Pi only!"
  exit 1
fi

if [[ "$(uname)" != "Linux" ]]; then
  echo "This script is intended to run on a Raspberry Pi with Linux only!"
  exit 1
fi

SELF="$0"
SWAP_FILE=/swapfile
SWAP_FILE_SIZE=1024
BASE_DIR="/usr/local"
APP_NAME="quadstick-display"

ARCHIVE_LINE=$(awk '/^__ARCHIVE_BELOW__/ {print NR + 1; exit 0; }' "$SELF")

CURRENT_STEP=0
LAST_STEP=$(awk '/^[[:space:]]+?__step / {count++} END {print count}' "$SELF")

__step() {
  local take_a_while="${1:-}"
  shift
  CURRENT_STEP=$((CURRENT_STEP + 1))
  echo
  echo "$CURRENT_STEP / $LAST_STEP Installing $*"
  if [[ -n "$take_a_while" ]]; then
    echo "  => This may take a while..."
  fi
}

USER=$(whoami)

echo
echo "Installing $APP_NAME for user $USER"

tail -n +"$ARCHIVE_LINE" "$SELF" >/tmp/archive.zip &&
  sudo unzip /tmp/archive.zip -d "$BASE_DIR" &&
  rm /tmp/archive.zip

sudo chown -R "${USER}:${USER}" "$BASE_DIR/$APP_NAME"

__step "" "Updating the system"
sudo apt-get update

__step "" "Setting up the locale"
sudo locale-gen en_US.UTF-8 -y

if ! grep -q $SWAP_FILE /etc/fstab; then
  __step "1" "Creating swapfile of size $SWAP_FILE_SIZE MiB at $SWAP_FILE"
  sudo dd if=/dev/zero of=$SWAP_FILE bs=1M count=$SWAP_FILE_SIZE
  sudo chmod 600 $SWAP_FILE
  sudo mkswap $SWAP_FILE
  sudo swapon $SWAP_FILE

  __step "" "Adding swapfile to fstab"
  echo "$SWAP_FILE    none    swap    defaults    0    0" | sudo tee -a /etc/fstab
else
  echo "Swapfile already exists at $SWAP_FILE"
  LAST_STEP=$((LAST_STEP - 2))
fi

__step "" "Enabling SPI interface"
if grep -q "#dtparam=spi=on" /boot/firmware/config.txt; then
  sudo sed -i 's/#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt
fi

if grep -q "dtparam=spi=off" /boot/firmware/config.txt; then
  sudo sed -i 's/dtparam=spi=off/dtparam=spi=on/' /boot/firmware/config.txt
fi

__step "" "Disabling Console on Serial Port"
if grep -q "console=serial0,115200" /boot/firmware/cmdline.txt; then
  sudo sed -i 's/console=serial0,115200//g' /boot/firmware/cmdline.txt
fi

__step "" "Disabling Serial Port"
if grep -q "enable_uart=1" /boot/firmware/config.txt; then
  sudo sed -i 's/enable_uart=1/enable_uart=0/' /boot/firmware/config.txt
fi

__step "" "Disabling Audio"
if grep -q "dtparam=audio=on" /boot/firmware/config.txt; then
  sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt
fi

__step "" "Disabling HDMI"
if grep -q "hdmi_force_hotplug=1" /boot/firmware/config.txt; then
  sudo sed -i 's/hdmi_force_hotplug=1/hdmi_force_hotplug=0/' /boot/firmware/config.txt
fi

__step "" "OS dependencies"

sudo apt-get install -yq zip unzip git

__step "1" "Python dependencies"
sudo apt-get install -yq \
  python3-pip \
  python3-pil \
  python3-numpy \
  python3-full \
  python3-spidev \
  python3-rpi.gpio \
  python3-gpiozero

__step "" "the application"

if [[ ! -d "$BASE_DIR/$APP_NAME" ]]; then
  echo "Error: $BASE_DIR/$APP_NAME not found!"
fi

__step "" "Creating virtual environment"
cd "$BASE_DIR/$APP_NAME" || exit 1
python3 -m venv venv

__step "" "Activating virtual environment"
. venv/bin/activate

__step "1" "Installing Python dependencies"
cd "$BASE_DIR/$APP_NAME" || exit 1

pip install -r "requirements.txt"

__step "" "Enabling the application via http"
HAS_HTTPD=$(sudo grep -c qs_display_httpd /etc/systemd/system/qs_display_httpd.service)
sudo chmod +x "$BASE_DIR/$APP_NAME/qs_display_httpd.sh"

sudo sed -ie "s/__USER__/$USER/" "$BASE_DIR/$APP_NAME/qs_display_httpd.service" 2>/dev/null
sudo sed -ie "s#__WORKING_DIRECTORY__#$BASE_DIR/$APP_NAME#g" "$BASE_DIR/$APP_NAME/qs_display_httpd.service" 2>/dev/null

sudo cp "$BASE_DIR/$APP_NAME/qs_display_httpd.service" /etc/systemd/system/qs_display_httpd.service
sudo systemctl daemon-reload

if [[ $HAS_HTTPD -eq 0 ]]; then
  sudo systemctl enable qs_display_httpd.service
  sudo systemctl start qs_display_httpd.service
else
  sudo systemctl restart qs_display_httpd.service
fi

__step "" "Cleaning up"
sudo apt-get autoremove -yq
sudo apt-get clean

echo
echo "Installation complete!"

echo "Rebooting in 5 seconds..."
sleep 5
sudo reboot

exit 0

__ARCHIVE_BELOW__
