{
  description = "Расширение AutoCAD 2021: изолинии мощностей и поле распределения KCl";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            # AutoCAD 2021 хостит .NET Framework 4.8, поэтому сам плагин
            # собирается в Windows-ВМ. Здесь SDK нужен для Task.Core
            # (netstandard2.0) и тестов (net8.0) — то есть для всей
            # алгоритмической части, которая разрабатывается на Linux.
            pkgs.dotnet-sdk_8

            # Служебные разборы дампов: пересчитать связи, найти дубли,
            # проверить диапазоны. Быстрее, чем поднимать ради этого базу.
            pkgs.python3
          ];

          # Пакет ставит SDK в share/dotnet; без явного DOTNET_ROOT дочерние
          # процессы (msbuild, тестовый раннер) его не находят.
          DOTNET_ROOT = "${pkgs.dotnet-sdk_8}/share/dotnet";
          DOTNET_CLI_TELEMETRY_OPTOUT = "1";
          DOTNET_NOLOGO = "1";

          shellHook = ''
            echo "dotnet $(dotnet --version)"
            echo "Oracle:  podman compose -f infra/compose.yaml up -d"
            echo "дампы:   ./infra/load-dumps.sh"
          '';
        };
      });
    };
}
