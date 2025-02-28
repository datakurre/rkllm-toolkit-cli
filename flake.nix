{
  description = "rkllm-toolkit-cli";
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-24.11";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.inputs.uv2nix.follows = "uv2nix";
    gitignore.url = "github:hercules-ci/gitignore.nix";
    gitignore.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      gitignore,
    }:
    let
      pkgs = import nixpkgs {
        config = {
          allowUnfree = true;
        };
        system = "x86_64-linux";
      };
    in
    {
      packages.x86_64-linux.rkllm-toolkit =
        let
          workspace = uv2nix.lib.workspace.loadWorkspace {
            workspaceRoot = (gitignore.lib.gitignoreSource ./.).outPath;
          };
          overlay = workspace.mkPyprojectOverlay {
            sourcePreference = "wheel";
          };
          pythonSet =
            (pkgs.callPackage pyproject-nix.build.packages {
              python = pkgs.python310;
            }).overrideScope
              (
                pkgs.lib.composeManyExtensions [
                  pyproject-build-systems.overlays.default
                  overlay
                  (import ./overrides.nix { pkgs = pkgs; })
                ]
              );
          inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;
        in
        mkApplication {
          venv = pythonSet.mkVirtualEnv "rkllm-toolkit-cli" workspace.deps.default;
          package = pythonSet.rkllm-toolkit-cli;
        };
      packages.x86_64-linux.default = self.packages.x86_64-linux.rkllm-toolkit;
    };
}
