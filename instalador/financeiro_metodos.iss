; Instalador do Financeiro Métodos (Inno Setup 6).
;
; Antes: gere o programa com o PyInstaller (instalador\financeiro_metodos.spec),
; que cria dist\FinanceiroMetodos. Depois compile este arquivo no Inno Setup
; (ou: iscc instalador\financeiro_metodos.iss). O instalador sai em instalador\saida.
;
; A versão vem só de src\honorarios\__init__.py: o gerar_instalador.bat a passa
; com /DVersao=... Compilando à mão, passe-a também (iscc /DVersao=x.y.z ...).
;
; Os dados (banco, backups) NÃO ficam na pasta do programa: são escolhidos no
; primeiro uso e continuam lá ao desinstalar ou atualizar.

#define Nome "Financeiro Métodos"
#ifndef Versao
  #error Falta a versão: use instalador\gerar_instalador.bat ou iscc /DVersao=x.y.z
#endif
#define Empresa "Métodos Serviços Contábeis"
#define Executavel "FinanceiroMetodos.exe"

[Setup]
; identificador fixo: atualizações reconhecem a instalação anterior (não troque)
AppId={{6F2C8E41-3B7D-4C5A-9E0F-8A1D2B3C4E5F}
AppName={#Nome}
AppVersion={#Versao}
AppVerName={#Nome} {#Versao}
AppPublisher={#Empresa}
VersionInfoVersion={#Versao}
VersionInfoProductVersion={#Versao}
VersionInfoCompany={#Empresa}
VersionInfoDescription=Instalador do {#Nome}
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
; instala sem pedir administrador (na pasta do usuário); quem for administrador
; pode escolher instalar para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=saida
OutputBaseFilename=Instalador_Financeiro_Metodos_{#Versao}
SetupIconFile=instalador.ico
UninstallDisplayIcon={app}\{#Executavel}
UninstallDisplayName={#Nome}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; o assistente com a identidade do Financeiro (scripts/gerar_icones.py), uma imagem
; por escala de tela do Windows
WizardImageFile=assistente_100.bmp,assistente_125.bmp,assistente_150.bmp,assistente_175.bmp,assistente_200.bmp,assistente_225.bmp,assistente_250.bmp
WizardSmallImageFile=assistente_pequeno_100.bmp,assistente_pequeno_125.bmp,assistente_pequeno_150.bmp,assistente_pequeno_175.bmp,assistente_pequeno_200.bmp,assistente_pequeno_225.bmp,assistente_pequeno_250.bmp
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "areadetrabalho"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\FinanceiroMetodos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "financeiro_metodos.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Executavel}"; IconFilename: "{app}\financeiro_metodos.ico"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Executavel}"; IconFilename: "{app}\financeiro_metodos.ico"; Tasks: areadetrabalho

[Run]
Filename: "{app}\{#Executavel}"; Description: "Abrir o {#Nome}"; Flags: nowait postinstall skipifsilent
; atualização pelo próprio sistema (instalador em /SILENT): abre o programa de novo
Filename: "{app}\{#Executavel}"; Flags: nowait skipifnotsilent
