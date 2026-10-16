##
# Copyright 2022-2026 Vrije Universiteit Brussel
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for Julia Packages, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Davide Grassano (CECAM, EPFL)
"""
import ast
import os
import re
import tempfile

from typing import List, Dict, Tuple, Union

from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.filetools import copy_dir
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.utilities import trace_msg, print_msg
from easybuild.tools.hooks import BUILD_STEP, TEST_STEP

from easybuild.easyblocks.julia import EB_JULIA_DEPOT_PATH_VAR, EB_JULIA_LOAD_PATH_VAR

_COMPILECACHE_CHECK = ' | '.join([
    # "julia -E 'Base.compilecache_path(Base.identify_package(\"%(ext_name)s\"), Base.get_world_counter())'",
    # compilecache_path is not part of the stable API and changes arguments across versions
    # allow internal cache resolution and use debug statements to get the path of the loaded cache
    "JULIA_DEBUG=loading julia -e 'using %(ext_name)s' 2>&1 1>/dev/null",
    "grep -E 'Loading (object )?cache file .*%(grep_loc)s'"
])

USER_DEPOT_PATTERN = re.compile(r"\/\.julia\/?(.*\.toml)*$")


class JuliaPackage(ExtensionEasyBlock):
    """
    Builds and installs Julia Packages.

    Julia environment setup during installation:
        - initialize new Julia environment in 'environments' subdir in installation directory
        - remove paths in user depot '~/.julia' from DEPOT_PATH and LOAD_PATH
        - put installation directory as top DEPOT_PATH, the target depot for installations with Pkg
        - put installation environment as top LOAD_PATH, needed to precompile installed packages
        - merge the environment of julia dependencies of this installation to the environment of this installation.
        - add newly installed Julia packages to installation environment
        - install all packages (main and deps) in parallel using Pkg.instantiate() command

    Julia environment setup on module load:
        User depot and its shared environment for this version of Julia are kept as top paths of DEPOT_PATH and
        LOAD_PATH respectively. This ensures that the user can keep using its own environment after loading
        JuliaPackage modules, installing additional software on its personal depot while still using packages
        provided by the module. Effectively, this translates to:
        - prepend installation directory to list of EB_JULIA_DEPOT_PATH, only really needed to load JLL artifacts
        - prepend installation Project.toml file to list of EB_JULIA_LOAD_PATH, needed to load packages with `using`
        - Generate JULIA_DEPOT_PATH by append the default DEPOT_PATH (:) to EB_JULIA_DEPOT_PATH
        - Generate JULIA_LOAD_PATH by prepending the default LOAD_PATH (:) to EB_JULIA_LOAD_PATH
          The prepending here is necessary as the default LOAD_PATH [@, @v#.#, @stdlib] can cause stdlib's packages
          that have been made upgradable (https://github.com/JuliaLang/julia/issues/50697) to fail matching the cache.
          See https://github.com/easybuilders/easybuild-easyblocks/issues/4123#issuecomment-4386990190 for more details.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to JuliaPackage."""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'download_pkg_deps': [
                False, "Let Julia download and bundle all needed dependencies for this installation", CUSTOM
            ],
            'is_test_dependency': [
                False,
                "Whether this package is only needed for testing and should not be added to installation environment",
                CUSTOM
            ],
            'julia_debug': [
                False,
                "Whether to set JULIA_DEBUG=all during installation and testing, to get more verbose output.",
                CUSTOM
            ],
            # Arguably this should be set to True by default. In many cases the test environment in Julia packages
            # will attempt to re-install the package being tested. If not all required packages to be  brought in the
            # test environment were specified in test/Project.toml, running Pkg.test() in offline mode will fail.
            # Some test tools like Aqua will also re-create their own tmp environment which can be broken even if
            # test/Project.toml is properly set up/patched.
            'test_online': [
                False,
                "Allow online tests that require downloading dependencies. By default, tests are run in offline mode.",
                CUSTOM
            ],
        })
        return extra_vars

    @staticmethod
    def get_julia_env(env_var):
        """
        Query environment variable to julia shell and parse it
        :param env_var: string with name of environment variable
        """
        julia_read_cmd = {
            "DEPOT_PATH": "julia -E 'Base.DEPOT_PATH'",
            "LOAD_PATH": "julia -E 'Base.load_path()'",
        }

        if env_var not in julia_read_cmd:
            raise EasyBuildError("Unknown Julia environment variable requested: %s", env_var)

        cmd = julia_read_cmd[env_var]

        res = run_shell_cmd(cmd, hidden=True)

        try:
            parsed_var = ast.literal_eval(res.output)
        except SyntaxError:
            raise EasyBuildError("Failed to parse %s from julia shell: %s", env_var, res.output)

        return parsed_var

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.cfg['is_test_dependency'] and not self.is_extension:
            raise EasyBuildError("Test dependencies can only be defined as an extension, not as a bundle itself")

        self._conflicts = []
        self._julia_deps = {}
        self._julia_deps_test = {}
        self._julia_version = None
        self._pkg_deps_included = False
        self._pkg_deps = []
        self._pkgs_to_test_online = []
        self._pkgs_to_test_offline = []
        self._tmp_test_dir = None
        self._installdir_created = False

    @property
    def julia_version(self) -> str:
        """Needs to get Julia version from dependencies to allow --sanity-check-only to generate the fake module"""
        if self._julia_version is None:
            deps = self.cfg.dependencies(runtime_only=True)
            for dep in deps:
                if dep['name'] == 'Julia':
                    self._julia_version = dep['version']
                    break
            else:
                raise EasyBuildError(
                    "Julia not included as dependency, cannot determine Julia version for installation of: %s",
                    self.name
                )
        return self._julia_version

    @property
    def conflicts(self) -> List[Tuple[str, str, str, str]]:
        """List of 4-tuple conflicting software (same package included from multiple locations) including:
        - extension name where conflict is found
        - package name with conflict
        - previous source of the package that caused the conflict
        - new source of the package that caused the conflict
        """
        if self.is_extension:
            return self.master.conflicts
        return self._conflicts

    @property
    def is_last_extension(self) -> bool:
        """Whether this extension is the last one to be installed."""
        if not self.is_extension:
            return True

        return self.master.ext_instances and self.master.ext_instances[-1] is self

    @property
    def julia_deps(self) -> Dict[str, str]:
        """List of Julia dependencies found in this installation excluding test dependencies
        - key: package name
        - value: package source
        """
        if self.is_extension:
            return self.master.julia_deps
        return self._julia_deps

    @property
    def julia_deps_test(self) -> Dict[str, str]:
        """List of Julia dependencies found in this installation including test dependencies
        - key: package name
        - value: package source
        """
        if self.is_extension:
            return self.master.julia_deps_test
        return self._julia_deps_test

    @property
    def pkg_deps(self) -> List[Tuple[str, str]]:
        """List of easybuild runtime dependencies that will need to be sanity-checked. 2-tuple including:
        - dependency name
        - dependency root (equivalent to get_software_root)
        """
        if self.is_extension:
            return self.master.pkg_deps
        return self._pkg_deps

    @property
    def pkgs_to_test_online(self) -> List[str]:
        """List extension names with `runtest` set to True that should be tested in online mode."""
        if self.is_extension:
            return self.master.pkgs_to_test_online
        return self._pkgs_to_test_online

    @property
    def pkgs_to_test_offline(self) -> List[str]:
        """List extension names with `runtest` set to True that should be tested in offline mode."""
        if self.is_extension:
            return self.master.pkgs_to_test_offline
        return self._pkgs_to_test_offline

    @property
    def tmp_test_dir(self) -> str:
        """Temporary path used for running the test step."""
        if self.is_extension:
            return self.master.tmp_test_dir

        if not self._tmp_test_dir:
            try:
                self._tmp_test_dir = tempfile.mkdtemp(suffix='-julia_tests')
            except Exception as e:
                raise EasyBuildError("Failed to create temporary directory for Julia package testing: %s", str(e))
        return self._tmp_test_dir

    def julia_env_path(self, absolute: bool = True, base: bool = True, basedir: Union[str, None] = None) -> str:
        """
        Return path to installation environment file.

        :param absolute: whether to return absolute path to environment file or relative path to `basedir`
        :param base: whether to return path to environment file or its parent directory
        :param basedir: base directory for the environment, as in env=BASEDIR/environments/v#.#/Project.toml.
        Defaults to installation directory of this package if not specified.
        """
        basedir = basedir or self.installdir
        julia_version = self.julia_version.split('.')
        env_dir = "v{}.{}".format(*julia_version[:2])
        project_env = os.path.join("environments", env_dir, "Project.toml")

        if absolute:
            project_env = os.path.join(basedir, project_env)
        if base:
            project_env = os.path.dirname(project_env)

        return project_env

    def set_pkg_remote(self, online: bool = False):
        """Enable online/offline mode of Julia Pkg"""

        julia_version = get_software_version('Julia')
        if LooseVersion(julia_version) >= LooseVersion('1.5'):
            # Enable offline mode of Julia Pkg
            # https://pkgdocs.julialang.org/v1/api/#Pkg.offline
            env.setvar('JULIA_PKG_OFFLINE', 'false' if online else 'true')
        else:
            errmsg = (
                "Cannot set offline mode in Julia v%s (needs Julia >= 1.5). "
                "Enable easyconfig option 'download_pkg_deps' to allow installation "
                "with any extra downloaded dependencies."
            )
            raise EasyBuildError(errmsg, julia_version)

    def prepare_julia_env(self, basedir: Union[str, None] = None, online: bool = False):
        """
        1. Remove user depot and prepend installation directory to DEPOT_PATH.
        Top directory in Julia DEPOT_PATH is the target installation directory.
        See https://docs.julialang.org/en/v1/manual/environment-variables/#JULIA_DEPOT_PATH

        2. We also need the installation environment in LOAD_PATH to be able to populate it with all packages from
        current installation and its dependencies, as well as be able to precompile newly installed packages.
        This is automatically done by Julia once DEPOT_PATH is changed through JULIA_DEPOT_PATH. However, that
        only happens if JULIA_LOAD_PATH is not already set, which is the case for our modules of JuliaPackages.
        See https://docs.julialang.org/en/v1/manual/environment-variables/#JULIA_LOAD_PATH

        3. Enable offline mode in Julia to avoid automatic downloads of packages.

        4. Enable automatic precompilation of packages after each build.

        5. Enable/disable debug mode in Julia to get more verbose output during installation and testing.

        :param basedir: base directory for the environment, as in env=BASEDIR/environments/v#.#/Project.toml.
        Defaults to installation directory of this package if not specified.
        :param online: whether to allow online operations of Julia Pkg
        """
        basedir = basedir or self.installdir
        # Grab both DEPOT_PATH and LOAD_PATH before any changes are made
        # given that Julia might automatically update LOAD_PATH from a change on DEPOT_PATH
        dirty_depot = self.get_julia_env("DEPOT_PATH")
        self.log.debug('DEPOT_PATH read from Julia environment: %s', os.pathsep.join(dirty_depot))
        dirty_load = self.get_julia_env("LOAD_PATH")
        self.log.debug('LOAD_PATH read from Julia environment: %s', os.pathsep.join(dirty_load))

        # First set DEPOT_PATH and then LOAD_PATH to avoid any automatic changes made by Julia
        clean_depot = [path for path in dirty_depot if not USER_DEPOT_PATTERN.search(path) and path != self.installdir]
        install_depot = os.pathsep.join([basedir] + clean_depot)
        self.log.debug("Preparing Julia 'DEPOT_PATH' for installation: %s", install_depot)
        env.setvar("JULIA_DEPOT_PATH", install_depot)

        project_toml = self.julia_env_path(base=False, basedir=basedir)
        clean_load = [path for path in dirty_load if not USER_DEPOT_PATTERN.search(path) and path != project_toml]
        install_load = os.pathsep.join([project_toml] + clean_load)
        self.log.debug("Preparing Julia 'LOAD_PATH' for installation: %s", install_load)
        env.setvar("JULIA_LOAD_PATH", install_load)

        # Disable EB controlled PATHS to enforce the specific configurations
        env.setvar(EB_JULIA_DEPOT_PATH_VAR, "")
        env.setvar(EB_JULIA_LOAD_PATH_VAR, "")

        if project_toml not in self.get_julia_env("LOAD_PATH"):
            errmsg = "Failed to prepare Julia environment for installation of: %s"
            raise EasyBuildError(errmsg, self.name)

        # Enable/disable offline mode
        self.set_pkg_remote(online=online)

        env.setvar('JULIA_DEBUG', 'all' if self.cfg['julia_debug'] else '')

        # Set the maximum number of concurrent package builds
        env.setvar('JULIA_NUM_PRECOMPILE_TASKS', str(self.cfg.parallel))
        # Enable automatic precompilation
        env.setvar('JULIA_PKG_PRECOMPILE_AUTO', 'true')

    def add_package(self, pkg_source, test_only=False):
        """Add a Julia package to the list of dependencies to be installed.

        :param pkg_source: path to the package source to be added as dependency
        :param test_only: whether this package is only needed for testing and should not be added to installation
        environment
        """
        pkg_name = os.path.basename(pkg_source)
        if pkg_name in self.julia_deps:
            prev_source = self.julia_deps[pkg_name]
            if prev_source != pkg_source:
                self.conflicts.append((self.name, pkg_name, prev_source, pkg_source))

        self.julia_deps_test[pkg_name] = pkg_source
        if not test_only:
            self.julia_deps[pkg_name] = pkg_source

    def _check_conflicts(self):
        """Check for conflicts in Julia dependencies and raise an error if any are found."""
        if self.conflicts:
            conflict_msgs = []
            for ext_name, pkg_name, prev_source, new_source in self.conflicts:
                conflict_msgs.append(
                    f"Conflict detected for package '{pkg_name}' in extension '{ext_name}': "
                    f"already added from source '{prev_source}', cannot add from source '{new_source}'"
                )
            raise EasyBuildError("Conflicts detected in Julia dependencies:\n" + "\n".join(conflict_msgs))

    def install_pkg(self, basedir: Union[str, None] = None):
        """Execute Julia.Pkg command to install all packages in `self.julia_deps` in the install environment.

        :param basedir: base directory for the environment, as in env=BASEDIR/environments/v#.#/Project.toml.
        Defaults to installation directory of this package if not specified
        """
        self._check_conflicts()
        basedir = basedir or self.installdir
        env = self.julia_env_path(basedir=basedir)

        if len(self.julia_deps) == 0:
            if len(self.julia_deps_test) > 0:
                raise EasyBuildError(
                    "Only test dependencies found for Julia package %s, cannot proceed with installation. "
                    "Please check that all needed dependencies are properly specified in the easyconfig file.",
                    self.name
                )
            raise EasyBuildError("No Julia packages to install for: %s", self.name)

        package_specs = ', '.join(f'PackageSpec(path="{path}")' for path in self.julia_deps.values())

        julia_pkg_cmd = [
            'using Pkg',
            f'Pkg.activate("{env}")',

            f'Pkg.develop([{package_specs}]; preserve=PRESERVE_ALL)',
            # Usage `Pkg.instantiate()` after all sources are in place to let Pkg handle all dependencies.
            # This has the advantage of letting Pkg deal with the order and parallel installation.
            'Pkg.instantiate()',
            # Ensure operations done only by build.jl are done for all packages if needed
            'Pkg.build()',
        ]

        julia_pkg_cmd = '; '.join(julia_pkg_cmd)
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            "julia -e '%s'" % julia_pkg_cmd,
            self.cfg['installopts'],
        ])
        res = run_shell_cmd(cmd)

        return res.output

    def _deps_from_project(self, environment: str) -> List[str]:
        """Get list of dependencies from a Julia environment

        :param environment: path to Julia environment to query for dependencies
        """
        julia_root = get_software_root('Julia')
        cmd = "; ".join([
            'using Pkg',
            f'Pkg.activate("{environment}")',
            'for (_, pkg) in Pkg.dependencies()',
            'println("$(pkg.source)")',
            'end'
        ])

        res = run_shell_cmd(f"julia -E '{cmd}'", split_stderr=True, hidden=True)
        deps = res.output.strip().splitlines()

        # Filter out Julia's stdlib dependencies
        deps = filter(lambda d: not d.startswith(julia_root), deps)
        deps = filter(lambda d: d != 'nothing', deps)

        return list(deps)

    def include_pkg_dependencies(self, add_subdeps: bool = True):
        """Add to installation environment all Julia packages already present in its dependencies

        :param add_subdeps: whether to also add sub-dependencies to the installation environment. Defaults to True,
          for actual installation. Should be set to False when used for `--sanity-check-only` or similar modes that
          skip the installation
        """
        if self._pkg_deps_included:
            return
        self._pkg_deps_included = True
        build_only_deps = self.cfg.dependencies(build_only=True)
        # add packages found in dependencies to this installation environment
        for dep in self.cfg.dependencies():
            dep_name = dep['name']
            dep_root = get_software_root(dep_name)
            dep_env = self.julia_env_path(absolute=True, base=True, basedir=dep_root)
            if not os.path.isdir(dep_env):
                self.log.warning("No environment directory found in dependency %s, skipping: %s", dep_name, dep_env)
                continue

            test_only = dep in build_only_deps
            if test_only:
                trace_msg(
                    f"Incorporating Julia package in TEST    environment {dep_name}: {dep_env}"
                )
            else:
                self.pkg_deps.append((dep_name, dep_root))
                trace_msg(
                    f"Incorporating Julia package in INSTALL environment {dep_name}: {dep_env}"
                )

            if add_subdeps:
                for pkg_path in self._deps_from_project(dep_env):
                    self.add_package(pkg_path, test_only=test_only)

    def make_installdir(self):
        """Create new installation directory and ensure this is done only once"""
        # Stop installdir from being re-created at the install step
        if not self._installdir_created:
            super().make_installdir()
            self._installdir_created = True

    def prepare_step(self, *args, **kwargs):
        """Prepare for Julia package installation."""
        super().prepare_step(*args, **kwargs)
        self.make_installdir()

        if get_software_root('Julia') is None:
            raise EasyBuildError("Julia not included as dependency!")

        self.include_pkg_dependencies()

    def configure_step(self):
        """Configure step for Julia packages is a no-op, as there is no configuration needed before installation."""
        pass

    def install_source(self):
        """Add the Julia package source files in the installation directory."""
        if self.cfg['is_test_dependency']:
            self.log.debug(
                f"Package {self.name} is only needed for testing, installing sources in {self.tmp_test_dir}"
            )
            trace_msg("Installing as a test dependency...")
            package_dir = os.path.join(self.tmp_test_dir, 'packages', self.name)
        else:
            package_dir = os.path.join(self.installdir, 'packages', self.name)

        copy_dir(self.start_dir, package_dir)
        self.add_package(package_dir, test_only=self.cfg['is_test_dependency'])

    def _build_install_step(self, basedir: Union[str, None] = None):
        """Install step commons between single-package and extensions based installs.

        :param basedir: base directory for the environment, as in env=BASEDIR/environments/v#.#/Project.toml.
        Defaults to installation directory of this package if not specified.
        """
        self.install_source()
        if self.is_last_extension:
            self.prepare_julia_env(basedir=basedir, online=self.cfg['download_pkg_deps'])
            return self.install_pkg(basedir=basedir)
        else:
            trace_msg("Delegating build+install to last extension")

    def build_step(self):
        """Build step for Julia packages is a no-op, as there is no build needed before installation."""
        return self._build_install_step()

    def test_step(self):
        """
        Test the built Julia package.

        :param return_output: return output and exit code of test command
        """
        if self.cfg['runtest']:
            if self.cfg['test_online']:
                self.pkgs_to_test_online.append(self.name)
            else:
                self.pkgs_to_test_offline.append(self.name)

        if not self.is_last_extension:
            trace_msg("Delegating testing to last extension")
            return

        env = self.julia_env_path(basedir=self.tmp_test_dir)
        testcmd = [
            'using Pkg',
            f'Pkg.activate("{env}")',
            # f'Pkg.develop([{pkg_specs}]; preserve=PRESERVE_ALL)',
            # 'Pkg.test([{pkg_test}])',
        ]
        if self.julia_deps_test:
            pkg_specs = ', '.join(f'PackageSpec(path="{path}")' for path in self.julia_deps_test.values())
            testcmd.append(f'Pkg.develop([{pkg_specs}]; preserve=PRESERVE_ALL)')
        testcmd.append('Pkg.test([{pkg_test}])')
        testcmd = '; '.join(testcmd)
        testcmd = f"julia -e '{testcmd}'"

        # Also add normal DEPOT/LOAD paths to environment to try and re-use pre-compiled caches as much as possible
        # But also ensure that artifacts for packages that do not need recompilation are still found in the tests
        self.prepare_julia_env()
        self.prepare_julia_env(basedir=self.tmp_test_dir)

        # Run offline tests first just in case the online ones could modify the environment
        if self.pkgs_to_test_offline:
            trace_msg("Running offline tests:")
            self.set_pkg_remote(online=False)
            pkg_test = ', '.join(f'"{pkg}"' for pkg in self.pkgs_to_test_offline)

            cmd = ' '.join([
                self.cfg['pretestopts'],
                testcmd.format(pkg_test=pkg_test),
                self.cfg['testopts'],
            ])

            res = run_shell_cmd(cmd, fail_on_error=False)

            if res.exit_code != 0:
                self.report_test_failure(f"Offline tests failed for Julia package {self.name}:\n{res.output}")

        if self.pkgs_to_test_online:
            trace_msg("Running online tests:")
            self.set_pkg_remote(online=True)
            pkg_test = ', '.join(f'"{pkg}"' for pkg in self.pkgs_to_test_online)

            cmd = ' '.join([
                self.cfg['pretestopts'],
                testcmd.format(pkg_test=pkg_test),
                self.cfg['testopts'],
            ])

            res = run_shell_cmd(cmd, fail_on_error=False)

            if res.exit_code != 0:
                self.report_test_failure(f"Tests failed for Julia package {self.name}:\n{res.output}")

    def install_step(self):
        """Install step for Julia packages is a no-op, as there is no build needed before installation."""
        pass

    def install_extension(self, *args, **kwargs):
        """Install Julia package as an extension."""
        if not self.src:
            errmsg = "No source found for Julia package %s, required for installation. (src: %s)"
            raise EasyBuildError(errmsg, self.name, self.src)

        super().install_extension(*args, unpack_src=True)

        steps = [
            (BUILD_STEP, 'building', [lambda x: x._build_install_step], True),
            (TEST_STEP, 'testing', [lambda x: x._test_step], True),
        ]
        self.skip = False  # --skip does not apply here
        self.silent = build_option('silent')
        # See EasyBlock.run_all_steps
        for (step_name, descr, step_methods, skippable) in steps:
            if self.skip_step(step_name, skippable):
                print_msg("\t%s [skipped]" % descr, log=self.log, silent=self.silent)
            else:
                if self.dry_run:
                    self.dry_run_msg("\t%s... [DRY RUN]\n", descr)
                else:
                    print_msg("\t%s..." % descr, log=self.log, silent=self.silent)
                    for step_method in step_methods:
                        step_method(self)()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for JuliaPackage"""
        if self.cfg['is_test_dependency']:
            self.log.debug(f"Package {self.name} is only used for testing, skipping sanity check")
            return (True, "Test dependency, skipping sanity check")

        cc_check = LooseVersion(self.julia_version) >= LooseVersion('1.8')

        if self.is_extension:
            pkg_dir = os.path.join('packages', self.name)

            custom_paths = {
                'files': [],
                'dirs': [pkg_dir],
            }

            exts_filter = []
            if cc_check:
                exts_filter.append(_COMPILECACHE_CHECK % {'ext_name': self.name, 'grep_loc': self.name})
            exts_filter.append("julia -e 'using %(ext_name)s'")
            exts_filter = " && ".join(exts_filter)
            self.cfg['exts_filter'] = (exts_filter, "")
        else:
            # Ensure `pkg_deps` is populated also in `--sanity-check-only` or similar modes
            self.include_pkg_dependencies(add_subdeps=False)
            custom_paths = {
                'files': [],
                'dirs': ['packages', 'environments'],
            }
            custom_commands = []
            if cc_check:
                for dep, _ in self.pkg_deps:
                    custom_commands.append(
                        _COMPILECACHE_CHECK % {'ext_name': dep, 'grep_loc': dep}
                    )
            kwargs.setdefault('custom_commands', []).extend(custom_commands)

        kwargs.update({'custom_paths': custom_paths})

        return super().sanity_check_step(*args, **kwargs)

    def make_module_extra(self, *args, **kwargs):
        """
        Set EB-specific PATH like variables `EB_JULIA_DEPOT_PATH` and `EB_JULIA_LOAD_PATH`.
        These are then used by Easybuild's custom Julia startup script (etc/julia/startup.jl) to set JULIA_DEPOT_PATH
        and JULIA_LOAD_PATH correctly at runtime.
        """
        mod = super().make_module_extra()

        mod += self.module_generator.prepend_paths(EB_JULIA_DEPOT_PATH_VAR, [''])
        mod += self.module_generator.prepend_paths(
            EB_JULIA_LOAD_PATH_VAR,
            [self.julia_env_path(absolute=False, base=True)]
        )

        return mod

    def make_extension_list(self):
        """Generate list of extensions while filtering out test dependencies."""
        exts = super().make_extension_list()
        test_dep_names = self.julia_deps_test.keys() - self.julia_deps.keys()

        return list(filter(lambda ext: ext[0] not in test_dep_names, exts))
