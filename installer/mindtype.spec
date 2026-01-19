# =============================================================================
# RPM Spec file for MindType
# Build: rpmbuild -bb mindtype.spec
# =============================================================================

%define app_name MindType
%define pkg_name mindtype
%define app_id com.mindtype.MindType

# Disable automatic dependency generation (we bundle everything)
%global __requires_exclude_from ^%{_libdir}/%{pkg_name}/.*$
%global __provides_exclude_from ^%{_libdir}/%{pkg_name}/.*$
AutoReqProv: no

Name:           %{pkg_name}
Version:        %{_version}
Release:        1%{?dist}
Summary:        Offline speech-to-text transcription using Whisper AI
License:        Proprietary
URL:            https://mindtype.app
Group:          Applications/Multimedia

Source0:        %{app_name}.tar.gz

BuildArch:      x86_64

# Runtime dependencies
Requires:       glibc
Requires:       libX11
Requires:       libxcb
Requires:       libxkbcommon
Requires:       mesa-libGL
Requires:       mesa-libEGL
Requires:       pulseaudio-libs

%description
MindType is a desktop application for transcribing speech to text
using OpenAI's Whisper AI model. It works completely offline without
sending any data to external servers.

Features:
- Push-to-talk recording with global hotkey
- Support for multiple Whisper models (tiny to large)
- Auto-paste transcribed text to any application
- Multi-language support with automatic detection
- VAD (Voice Activity Detection) for smart recording

%prep
%setup -q -n %{app_name}

%install
rm -rf %{buildroot}

# Create directories
mkdir -p %{buildroot}%{_libdir}/%{pkg_name}
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/16x16/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/32x32/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/48x48/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/64x64/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/128x128/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/256x256/apps
mkdir -p %{buildroot}%{_datadir}/metainfo

# Copy application files
cp -R * %{buildroot}%{_libdir}/%{pkg_name}/

# Create launcher symlink
ln -sf %{_libdir}/%{pkg_name}/%{app_name} %{buildroot}%{_bindir}/%{pkg_name}

# Desktop file
cat > %{buildroot}%{_datadir}/applications/%{app_id}.desktop << EOF
[Desktop Entry]
Type=Application
Name=MindType
GenericName=Speech to Text
Comment=Offline speech-to-text transcription using Whisper AI
Exec=%{pkg_name} %%F
Icon=%{app_id}
Categories=AudioVideo;Audio;Utility;
Keywords=speech;voice;transcription;whisper;ai;dictation;
Terminal=false
StartupNotify=true
StartupWMClass=%{app_name}
EOF

# AppStream metainfo
cat > %{buildroot}%{_datadir}/metainfo/%{app_id}.metainfo.xml << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>%{app_id}</id>
  <name>MindType</name>
  <summary>Offline speech-to-text transcription</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>Proprietary</project_license>
  <description>
    <p>
      MindType is a desktop application for transcribing speech to text
      using OpenAI's Whisper AI model. It works completely offline.
    </p>
  </description>
  <launchable type="desktop-id">%{app_id}.desktop</launchable>
  <url type="homepage">https://mindtype.app</url>
  <provides>
    <binary>%{pkg_name}</binary>
  </provides>
  <releases>
    <release version="%{version}" date="%(date +%%Y-%%m-%%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF

%post
# Update icon cache
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
fi

# Update desktop database
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database %{_datadir}/applications &>/dev/null || :
fi

%postun
# Update icon cache
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
fi

# Update desktop database
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database %{_datadir}/applications &>/dev/null || :
fi

%files
%defattr(-,root,root,-)
%{_libdir}/%{pkg_name}
%{_bindir}/%{pkg_name}
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/metainfo/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{app_id}.png

%changelog
* %(date "+%a %b %d %Y") MindType Team <support@mindtype.app> - %{version}-1
- Release version %{version}












