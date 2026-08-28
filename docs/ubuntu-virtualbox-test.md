# Ubuntu VirtualBox Test Environment

This setup tests X11 and AT-SPI in a real Ubuntu Desktop session. It does not use WSL or a headless server.

1. Install VirtualBox for Windows.
2. Download an Ubuntu Desktop ISO, for example Ubuntu 24.04 LTS.
3. From the repository root, create and open the VM:

```powershell
.\scripts\create_ubuntu_test_vm.ps1 -IsoPath "$HOME\Downloads\ubuntu-24.04.2-desktop-amd64.iso" -Start
```

4. Complete the standard Ubuntu Desktop installation and install VirtualBox Guest Additions.
5. In the Ubuntu VM, open a terminal and run:

```bash
bash /media/sf_TraineeAI/scripts/ubuntu/install_linux_collector.sh
```

6. Start Chromium with Chrome DevTools Protocol enabled, then run the Linux and browser collectors as printed by the installer.

The VirtualBox shared folder exposes the Windows checkout at `/media/sf_TraineeAI`. The collectors write `events.jsonl` and `browser-events.jsonl` in that shared checkout.
