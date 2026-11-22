; Daybook CRM - Windows installer (NSIS 3). Per-user install: no admin rights, no UAC prompt.
; Built by crm/tools/package-windows.sh inside the build container:
;   makensis -DVERSION=0.1.0 installer.nsi   (next to daybook-crm.exe, WebView2Loader.dll, icon.ico)
Unicode true
!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!define APP "Daybook CRM"
!define EXE "daybook-crm.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\DaybookCRM"

Name "${APP}"
OutFile "DaybookCRM-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Daybook CRM"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Daybook CRM ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "CompanyName" "Daybook"
VIAddVersionKey "FileDescription" "${APP} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Daybook"

!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "${APP}"
!define MUI_WELCOMEPAGE_TEXT "Dorixonalar uchun CRM. CRM для аптек. The CRM built for pharmacies.$\r$\n$\r$\nWindows, Android, iPhone - one Rust app, works offline, connects to Daybook."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Daybook CRM"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

Function .onInit
  ; The app draws its window with Microsoft Edge WebView2 (built into Windows 11).
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 done
  ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 done
  MessageBox MB_YESNO|MB_ICONINFORMATION "Daybook CRM needs Microsoft Edge WebView2 Runtime, which is missing on this PC.$\r$\nOpen the Microsoft download page now?" IDNO done
  ExecShell "open" "https://developer.microsoft.com/microsoft-edge/webview2/"
  done:
FunctionEnd

Section "Daybook CRM" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "${EXE}"
  File "WebView2Loader.dll"
  File "icon.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Daybook CRM"
  CreateShortcut "$SMPROGRAMS\Daybook CRM\Daybook CRM.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\icon.ico" 0
  CreateShortcut "$SMPROGRAMS\Daybook CRM\Uninstall Daybook CRM.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Daybook CRM.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\icon.ico" 0
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Daybook"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\WebView2Loader.dll"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\Daybook CRM\Daybook CRM.lnk"
  Delete "$SMPROGRAMS\Daybook CRM\Uninstall Daybook CRM.lnk"
  RMDir "$SMPROGRAMS\Daybook CRM"
  Delete "$DESKTOP\Daybook CRM.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ; The customer data in %LOCALAPPDATA%\Daybook CRM stays, so a reinstall keeps it.
SectionEnd
