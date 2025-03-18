##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for software that is configured with CMake, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Maxime Boissonneault (Compute Canada - Universite Laval)
"""
import glob
import re
import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import BUILD, CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, create_unused_dir, mkdir, read_file, which
from easybuild.tools.environment import setvar
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.utilities import nub
import easybuild.tools.toolchain as toolchain


DEFAULT_CONFIGURE_CMD = 'cmake'


def det_cmake_version():
    """
    Determine active CMake version.
    """
    cmake_version = get_software_version('CMake')
    if cmake_version is None:
        # also take into account release candidate versions
        regex = re.compile(r"^[cC][mM]ake version (?P<version>[0-9]\.[0-9a-zA-Z.-]+)$", re.M)

        cmd = "cmake --version"
        cmd_res = run_shell_cmd(cmd, hidden=True, fail_on_error=False)
        out = cmd_res.output
        res = regex.search(out)
        if res:
            cmake_version = res.group('version')
        else:
            raise EasyBuildError("Failed to determine CMake version from output of '%s': %s", cmd, out)

    return cmake_version


def setup_cmake_env(tc):
    """Setup env variables that cmake needs in an EasyBuild context."""

    # Set the search paths for CMake
    tc_ipaths = tc.get_variable("CPPFLAGS", list)
    tc_lpaths = tc.get_variable("LDFLAGS", list)
    cpaths = os.getenv('CPATH', '').split(os.pathsep)
    lpaths = os.getenv('LD_LIBRARY_PATH', '').split(os.pathsep)
    include_paths = os.pathsep.join(nub(tc_ipaths + cpaths))
    library_paths = os.pathsep.join(nub(tc_lpaths + lpaths))
    setvar("CMAKE_INCLUDE_PATH", include_paths)
    setvar("CMAKE_LIBRARY_PATH", library_paths)


def setup_cmake_env_python_hints(cmake_version=None):
    """Set environment variables as hints for CMake to prefer the Python module, if loaded.
    Useful when there is no way to specify arguments for CMake directly,
    e.g. when CMake is called from within another build system.
    Otherwise get_cmake_python_config_[str/dict] should be used instead.
    """
    if cmake_version is None:
        cmake_version = det_cmake_version()
    if LooseVersion(cmake_version) < '3.12':
        raise EasyBuildError("Setting Python hints for CMake requires CMake version 3.12 or newer")
    python_root = get_software_root('Python')
    if python_root:
        python_version = LooseVersion(get_software_version('Python'))
        setvar('Python_ROOT_DIR', python_root)
        if python_version >= "3":
            setvar('Python3_ROOT_DIR', python_root)
        else:
            setvar('Python2_ROOT_DIR', python_root)


def get_cmake_python_config_dict():
    """Get a dictionary with CMake configuration options for finding Python if loaded as a module."""
    options = {}
    python_root = get_software_root('Python')
    if python_root:
        python_version = LooseVersion(get_software_version('Python'))
        python_exe = os.path.join(python_root, 'bin', 'python')
        # This is required for (deprecated) `find_package(PythonInterp ...)`
        options['PYTHON_EXECUTABLE'] = python_exe
        # Ensure that both `find_package(Python) and find_package(Python2/3)` work as intended
        options['Python_EXECUTABLE'] = python_exe
        if python_version >= "3":
            options['Python3_EXECUTABLE'] = python_exe
        else:
            options['Python2_EXECUTABLE'] = python_exe
    return options


def get_cmake_python_config_str():
    """Get CMake configuration arguments for finding Python if loaded as a module.
    This string is intended to be passed to the invocation of `cmake`.
    """
    options = get_cmake_python_config_dict()
    return ' '.join('-D%s=%s' % (key, value) for key, value in options.items())


class CMakeMake(ConfigureMake):
    """Support for configuring build with CMake instead of traditional configure script"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to CMakeMake."""
        extra_vars = ConfigureMake.extra_options(extra_vars)
        extra_vars.update({
            'abs_path_compilers': [False, "Specify compilers via absolute file path (not via command names)", CUSTOM],
            'allow_system_boost': [False, "Always allow CMake to pick up on Boost installed in OS "
                                          "(even if Boost is included as a dependency)", CUSTOM],
            'build_shared_libs': [None, "Build shared library (instead of static library)"
                                        "None can be used to add no flag (usually results in static library)", CUSTOM],
            'build_type': [None, "Build type for CMake, e.g. Release."
                                 "Defaults to 'Release', 'RelWithDebInfo' or 'Debug' depending on "
                                 "toolchainopts[debug,noopt]", CUSTOM],
            'configure_cmd': [DEFAULT_CONFIGURE_CMD, "Configure command to use", CUSTOM],
            'generator': [None, "Build file generator to use. None to use CMakes default", CUSTOM],
            'install_target_subdir': [None, "Subdirectory to use as installation target", CUSTOM],
            'install_libdir': ['lib', "Subdirectory to use for library installation files", CUSTOM],
            'runtest': [None, "Make target to test build or True to use CTest", BUILD],
            'srcdir': [None, "Source directory location to provide to cmake command", CUSTOM],
            'separate_build_dir': [True, "Perform build in a separate directory", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for CMakeMake easyblock"""
        super(CMakeMake, self).__init__(*args, **kwargs)
        self._lib_ext = None
        self._cmake_version = None
        self.separate_build_dir = None

    @property
    def lib_ext(self):
        """Return the extension for libraries build based on `build_shared_libs` or None if that is unset"""
        if self._lib_ext is None:
            build_shared_libs = self.cfg.get('build_shared_libs')
            if build_shared_libs:
                self._lib_ext = get_shared_lib_ext()
            elif build_shared_libs is not None:
                self._lib_ext = 'a'
        return self._lib_ext

    @lib_ext.setter
    def lib_ext(self, value):
        self._lib_ext = value

    @property
    def cmake_version(self):
        """Return the used CMake version, caching the value for reuse"""
        if self._cmake_version is None:
            self._cmake_version = det_cmake_version()
            self.log.debug('Determined CMake version: %s', self._cmake_version)
        return self._cmake_version

    @property
    def build_type(self):
        """Build type set in the EasyConfig with default determined by toolchainopts"""
        build_type = self.cfg.get('build_type')
        if build_type is None:
            if self.toolchain.options.get('noopt', None):  # also implies debug but is the closest match
                build_type = 'Debug'
            elif self.toolchain.options.get('debug', None):
                build_type = 'RelWithDebInfo'
            else:
                build_type = 'Release'
        return build_type

    def prepend_config_opts(self, config_opts):
        """Prepends configure options (-Dkey=value) to configopts ignoring those already set"""
        # need to disable template resolution or it will remain the same for all runs
        with self.cfg.disable_templating():
            cfg_configopts = self.cfg['configopts']

        # All options are of the form '-D<key>=<value>'
        new_opts = ' '.join('-D%s=%s' % (key, value) for key, value in config_opts.items()
                            if '-D%s=' % key not in cfg_configopts)
        self.cfg['configopts'] = ' '.join([new_opts, cfg_configopts])

    def configure_step(self, srcdir=None, builddir=None):
        """Configure build using cmake"""

        setup_cmake_env(self.toolchain)

        if builddir is None and self.cfg.get('separate_build_dir', True):
            self.separate_build_dir = create_unused_dir(self.builddir, 'easybuild_obj')
            builddir = self.separate_build_dir

        if builddir:
            mkdir(builddir, parents=True)
            change_dir(builddir)
            default_srcdir = self.cfg['start_dir']
        else:
            default_srcdir = '.'

        if srcdir is None:
            if self.cfg.get('srcdir', None) is not None:
                # Note that the join returns srcdir if it is absolute
                srcdir = os.path.join(default_srcdir, self.cfg['srcdir'])
            else:
                srcdir = default_srcdir

        install_target = self.installdir
        install_target_subdir = self.cfg.get('install_target_subdir')
        if install_target_subdir:
            install_target = os.path.join(install_target, install_target_subdir)
        options = {'CMAKE_INSTALL_PREFIX': install_target}

        if self.installdir.startswith('/opt') or self.installdir.startswith('/usr'):
            # https://cmake.org/cmake/help/latest/module/GNUInstallDirs.html
            localstatedir = os.path.join(self.installdir, 'var')
            runstatedir = os.path.join(localstatedir, 'run')
            sysconfdir = os.path.join(self.installdir, 'etc')
            options['CMAKE_INSTALL_LOCALSTATEDIR'] = localstatedir
            options['CMAKE_INSTALL_RUNSTATEDIR'] = runstatedir
            options['CMAKE_INSTALL_SYSCONFDIR'] = sysconfdir

        if '-DCMAKE_BUILD_TYPE=' in self.cfg['configopts']:
            if self.cfg.get('build_type') is not None:
                self.log.info("CMAKE_BUILD_TYPE is set in configopts. Ignoring 'build_type' easyconfig parameter.")
        else:
            options['CMAKE_BUILD_TYPE'] = self.build_type

        # Set installation directory for libraries
        # any CMAKE_INSTALL_DIR[:PATH] setting defined in 'configopts' has precedence over 'install_libdir'
        if self.cfg['install_libdir'] is not None:
            cmake_install_dir_pattern = re.compile(r"-DCMAKE_INSTALL_LIBDIR(:PATH)?=[^\s]")
            if cmake_install_dir_pattern.search(self.cfg['configopts']):
                self.log.info(
                    "CMAKE_INSTALL_LIBDIR is set in configopts. Ignoring 'install_libdir' easyconfig parameter."
                )
            else:
                # set CMAKE_INSTALL_LIBDIR including its type to PATH, otherwise CMake can silently ignore it
                options['CMAKE_INSTALL_LIBDIR:PATH'] = self.cfg['install_libdir']

        # Add -fPIC flag if necessary
        if self.toolchain.options.get('pic', False):
            options['CMAKE_POSITION_INDEPENDENT_CODE'] = 'ON'

        if self.cfg['generator']:
            generator = '-G "%s"' % self.cfg['generator']
        else:
            generator = ''

        # pass --sysroot value down to CMake,
        # and enable using absolute paths to compiler commands to avoid
        # that CMake picks up compiler from sysroot rather than toolchain compiler...
        sysroot = build_option('sysroot')
        if sysroot:
            options['CMAKE_SYSROOT'] = sysroot
            self.log.info("Using absolute path to compiler commands because of alterate sysroot %s", sysroot)
            self.cfg['abs_path_compilers'] = True

        # Set flag for shared libs if requested
        # Not adding one allows the project to choose a default
        build_shared_libs = self.cfg.get('build_shared_libs')
        if build_shared_libs is not None:
            # Contrary to other options build_shared_libs takes precedence over configopts which may be unexpected.
            # This is to allow self.lib_ext to be determined correctly.
            # Usually you want to remove -DBUILD_SHARED_LIBS from configopts and set build_shared_libs to True or False
            # If you need it in configopts don't set build_shared_libs (or explicitely set it to `None` (Default))
            if '-DBUILD_SHARED_LIBS=' in self.cfg['configopts']:
                print_warning('Ignoring BUILD_SHARED_LIBS setting in configopts because build_shared_libs is set')
            self.cfg.update('configopts', '-DBUILD_SHARED_LIBS=%s' % ('ON' if build_shared_libs else 'OFF'))

        # If the cache does not exist CMake reads the environment variables
        cache_exists = os.path.exists('CMakeCache.txt')
        env_to_options = dict()

        # Setting compilers is not required unless we want absolute paths
        if self.cfg.get('abs_path_compilers', False) or cache_exists:
            env_to_options.update({
                'CC': 'CMAKE_C_COMPILER',
                'CXX': 'CMAKE_CXX_COMPILER',
                'F90': 'CMAKE_Fortran_COMPILER',
            })
        else:
            # Set the variable which CMake uses to init the compiler using F90 for backward compatibility
            fc = os.getenv('F90')
            if fc:
                setvar('FC', fc)

        # Flags are read from environment variables already since at least CMake 2.8.0
        if LooseVersion(self.cmake_version) < LooseVersion('2.8.0') or cache_exists:
            env_to_options.update({
                'CFLAGS': 'CMAKE_C_FLAGS',
                'CXXFLAGS': 'CMAKE_CXX_FLAGS',
                'FFLAGS': 'CMAKE_Fortran_FLAGS',
            })

        for env_name, option in env_to_options.items():
            value = os.getenv(env_name)
            if value is not None:
                if option.endswith('_COMPILER') and self.cfg.get('abs_path_compilers', False):
                    value = which(value)
                    self.log.info("Using absolute path to compiler command: %s", value)
                options[option] = value

        if build_option('rpath') and LooseVersion(self.cmake_version) < LooseVersion('3.5.0'):
            # instruct CMake not to fiddle with RPATH when --rpath is used, since it will undo stuff on install...
            # this is only required for CMake < 3.5.0, since newer version are more careful w.r.t. RPATH,
            # see https://github.com/Kitware/CMake/commit/3ec9226779776811240bde88a3f173c29aa935b5
            options['CMAKE_SKIP_RPATH'] = 'ON'

        # show what CMake is doing by default
        options['CMAKE_VERBOSE_MAKEFILE'] = 'ON'

        # disable CMake user package repository
        options['CMAKE_FIND_USE_PACKAGE_REGISTRY'] = 'OFF'

        # ensure CMake uses EB python, not system or virtualenv python
        options.update(get_cmake_python_config_dict())

        # pass the preferred host compiler, CUDA compiler, and CUDA architectures to the CUDA compiler
        cuda_root = get_software_root('CUDA')
        if cuda_root:
            options['CMAKE_CUDA_HOST_COMPILER'] = which(os.getenv('CXX', 'g++'))
            options['CMAKE_CUDA_COMPILER'] = which('nvcc')
            cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']
            if cuda_cc:
                options['CMAKE_CUDA_ARCHITECTURES'] = '"%s"' % ';'.join([cc.replace('.', '') for cc in cuda_cc])
            else:
                raise EasyBuildError('List of CUDA compute capabilities must be specified, either via '
                                     'cuda_compute_capabilities easyconfig parameter or via '
                                     '--cuda-compute-capabilities')

        if not self.cfg.get('allow_system_boost', False):
            boost_root = get_software_root('Boost')
            if boost_root:
                # Check for older builds of Boost
                cmake_files = glob.glob(os.path.join(boost_root, 'lib', 'cmake', 'boost_system*',
                                                     'libboost_system-variant*-shared.cmake'))
                cmake_files = [os.path.basename(x) for x in cmake_files]
                if len(cmake_files) > 1 and 'libboost_system-variant-shared.cmake' in cmake_files:
                    # disable search for Boost CMake package configuration files when conflicting variant configs
                    # are present (builds using the old EasyBlock)
                    options['Boost_NO_BOOST_CMAKE'] = 'ON'

                # Don't pick up on system Boost if Boost is included as dependency
                # - specify Boost location via -DBOOST_ROOT
                # - instruct CMake to not search for Boost headers/libraries in other places
                options['BOOST_ROOT'] = boost_root
                options['Boost_NO_SYSTEM_PATHS'] = 'ON'

        self.cmake_options = options

        if self.cfg.get('configure_cmd') == DEFAULT_CONFIGURE_CMD:
            self.prepend_config_opts(options)
            command = ' '.join([
                self.cfg['preconfigopts'],
                DEFAULT_CONFIGURE_CMD,
                generator,
                self.cfg['configopts'],
                srcdir])
        else:
            command = ' '.join([
                self.cfg['preconfigopts'],
                self.cfg.get('configure_cmd'),
                self.cfg['configopts']])

        res = run_shell_cmd(command)
        self.check_python_paths()
        return res.output

    def check_python_paths(self):
        """Check that there are no detected Python paths outside the Python dependency provided by EasyBuild"""
        if not os.path.exists('CMakeCache.txt'):
            self.log.warning("CMakeCache.txt not found. Python paths checks skipped.")
            return
        cmake_cache = read_file('CMakeCache.txt')
        if not cmake_cache:
            self.log.warning("CMake Cache could not be read. Python paths checks skipped.")
            return

        self.log.info("Checking Python paths")

        python_paths = {
            "executable": [],
            "include_dir": [],
            "library": [],
        }
        python_regex = re.compile(r"_?(Python|PYTHON)\d?_"
                                  r"(?P<type>EXECUTABLE|INCLUDE_DIR|LIBRARY)\w*(:\w+)?\s*=(?P<value>.*)")
        cmake_false_expressions = {'', '0', 'OFF', 'NO', 'FALSE', 'N', 'IGNORE', 'NOTFOUND'}
        for line in cmake_cache.splitlines():
            match = python_regex.match(line)
            if match:
                self.log.debug("Python related CMake cache line found: " + line)
                path_type = match['type'].lower()
                path = match['value'].strip()
                if path.endswith('-NOTFOUND') or path.upper() in cmake_false_expressions:
                    continue
                self.log.info("Python %s path: %s", path_type, path)
                python_paths[path_type].append(path)

        ebrootpython_path = get_software_root("Python")
        if not ebrootpython_path:
            if any(python_paths.values()) and not self.toolchain.comp_family() == toolchain.SYSTEM:
                self.log.warning("Found Python paths in CMake cache but Python is not a dependency")
            # Can't do the check
            return
        ebrootpython_path = os.path.realpath(ebrootpython_path)

        errors = []
        for path_type, paths in python_paths.items():
            for path in paths:
                if not os.path.exists(path):
                    errors.append("Python %s path does not exist: %s" % (path_type, path))
                elif not os.path.realpath(path).startswith(ebrootpython_path):
                    errors.append("Python %s path '%s' is outside EBROOTPYTHON (%s)" %
                                  (path_type, path, ebrootpython_path))

        if errors:
            # Combine all errors into a single message
            error_message = "\n".join(errors)
            raise EasyBuildError("Python path errors:\n" + error_message)
        self.log.info("Python check successful")

    def test_step(self):
        """CMake specific test setup"""
        # When using ctest for tests (default) then show verbose output if a test fails
        setvar('CTEST_OUTPUT_ON_FAILURE', 'True')
        # Handle `runtest = True` if `test_cmd` has not been set
        if self.cfg.get('runtest') is True and not self.cfg.get('test_cmd'):
            test_cmd = 'ctest'
            if LooseVersion(self.cmake_version) >= '3.17.0':
                test_cmd += ' --no-tests=error'
            self.log.debug("`runtest = True` found, using '%s' as test_cmd", test_cmd)
            self.cfg['test_cmd'] = test_cmd

        super(CMakeMake, self).test_step()
