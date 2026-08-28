param(
    [Parameter(Mandatory)]
    [string]$IsoPath,
    [string]$VmName = "TraineeAI-Ubuntu",
    [int]$MemoryMb = 4096,
    [int]$CpuCount = 2,
    [int]$DiskSizeMb = 40960,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$vboxManage = Join-Path $env:ProgramFiles "Oracle\VirtualBox\VBoxManage.exe"

if (-not (Test-Path -LiteralPath $vboxManage)) {
    throw "VirtualBox was not found. Install it from https://www.virtualbox.org/ and run this script again."
}
if (-not (Test-Path -LiteralPath $IsoPath)) {
    throw "Ubuntu ISO was not found: $IsoPath"
}
if ((& $vboxManage list vms) -match ('"' + [regex]::Escape($VmName) + '"')) {
    throw "A VM named '$VmName' already exists. Choose -VmName or remove it in VirtualBox."
}

$vmDir = Join-Path $env:USERPROFILE "VirtualBox VMs\$VmName"
$diskPath = Join-Path $vmDir "$VmName.vdi"

& $vboxManage createvm --name $VmName --ostype Ubuntu_64 --register
& $vboxManage modifyvm $VmName --memory $MemoryMb --cpus $CpuCount --vram 128 --graphicscontroller vmsvga --accelerate3d on --nic1 nat
& $vboxManage storagectl $VmName --name "SATA" --add sata --controller IntelAhci
& $vboxManage createmedium disk --filename $diskPath --size $DiskSizeMb --format VDI
& $vboxManage storageattach $VmName --storagectl "SATA" --port 0 --device 0 --type hdd --medium $diskPath
& $vboxManage storageattach $VmName --storagectl "SATA" --port 1 --device 0 --type dvddrive --medium $IsoPath
& $vboxManage sharedfolder add $VmName --name TraineeAI --hostpath $rootDir --automount

Write-Host "VM '$VmName' created."
Write-Host "Install Ubuntu Desktop in the VirtualBox window, then run:"
Write-Host "  bash /media/sf_TraineeAI/scripts/ubuntu/install_linux_collector.sh"

if ($Start) {
    & $vboxManage startvm $VmName --type gui
}
