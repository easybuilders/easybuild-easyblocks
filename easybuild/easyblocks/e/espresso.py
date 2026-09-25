##
# Copyright 2025-2026 Jean-Noël Grad
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
EasyBuild support for ESPResSo, implemented as an easyblock.

@author: Jean-Noël Grad (University of Stuttgart)
"""

import os
import re

from easybuild.easyblocks.generic.cmakeninja import CMakeNinja
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file, remove_dir, remove_file, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_cpu_features, get_shared_lib_ext
from easybuild.tools.utilities import trace_msg


class EB_ESPResSo(CMakeNinja):
    """Support for building and installing ESPResSo."""

    def _get_extracted_tarball_paths(self):
        """
        Locate the source code of all dependencies.
        """
        extracted_paths = {}
        for src in self.src:
            name = src['name'].split('-', 1)[0]
            # process main software
            if name == 'espresso':
                extracted_paths['espresso'] = src['finalpath']
                continue
            # process dependencies
            tarball = src['name']
            if tarball.endswith(('.tar.bz2', '.tar.gz', '.tar.xz', '.tar.lz', '.tar.lz4', '.tar.Z')):
                prefix = tarball.rsplit('.', 2)[0]
            elif tarball.endswith(('.zip', '.7z', '.tar')):
                prefix = tarball.rsplit('.', 1)[0]
            else:
                raise EasyBuildError(f'unexpected archive/compression format: {tarball}')
            matches = [x for x in os.listdir(src['finalpath']) if x.lower().startswith(prefix.lower())]
            if len(matches) == 0:
                raise EasyBuildError(f'{tarball} was not extracted')
            if len(matches) > 1:
                raise EasyBuildError(f'{tarball} matches multiple folders: {matches}')
            extracted_paths[name] = os.path.join(src['finalpath'], matches[0])
        return extracted_paths

    def _patch_fetchcontent(self):
        """
        Modify CMake ``FetchContent_Declare`` blocks to point to the folders
        containing the already-downloaded dependencies rather than to URLs.
        This avoids a download step during configuration.
        """
        extracted_paths = self._get_extracted_tarball_paths()
        if 'espresso' in extracted_paths.keys():
            cmakelists_path = os.path.join(extracted_paths['espresso'], 'CMakeLists.txt')
        else:
            raise EasyBuildError(f"espresso not found in extracted_paths dict: {extracted_paths}")

        content = read_file(cmakelists_path)

        for name, local_uri in extracted_paths.items():
            if name == 'espresso':
                continue
            pattern = fr'FetchContent_Declare\(\s*{name}\s+GIT_REPOSITORY\s+\S+\s+GIT_TAG\s+\S+(?=\s|\))'
            m = re.search(pattern, content, flags=re.IGNORECASE)
            if m is None:
                raise EasyBuildError(f'{name} is not part of the ESPResSo FetchContent workflow')
            content = re.sub(pattern, f'FetchContent_Declare({name} URL {local_uri}', content, flags=re.IGNORECASE)

        write_file(cmakelists_path, content)

    def _get_version(self):
        """
        Internal helper function to get the ESPResSo version.
        """
        if '.' in self.version:
            version = tuple(LooseVersion(self.version).version)
        else:
            version = 'commit'
        return version

    def _set_exe_linker_flags(self):
        """
        Internal helper function to set the -DCMAKE_EXE_LINKER_FLAGS configure option.
        """
        exe_linker_flags_relpaths = []
        if get_software_root('HeFFTe'):
            exe_linker_flags_relpaths.append('heffte-build')
        if get_software_root('Kokkos'):
            exe_linker_flags_relpaths += [
                'kokkos-build/containers/src',
                'kokkos-build/core/src',
                'kokkos-build/simd/src',
            ]
        if exe_linker_flags_relpaths:
            # workaround for https://gitlab.kitware.com/cmake/cmake/-/issues/22678
            # (this only affects testsuite executable files in the build folder)
            exe_linker_flags = ':'.join(f'{self.builddir}/easybuild_obj/_deps/{path}'
                                        for path in exe_linker_flags_relpaths)
            self.cfg.update('configopts', f' -DCMAKE_EXE_LINKER_FLAGS="-Wl,-rpath-link,{exe_linker_flags}" ')

    def _set_configure_options_release_420(self):
        """
        Internal helper function to set configure options for ESPResSo v4.2+ (< 5.0).
        """
        for dep in ['CUDA', 'GSL', 'FFTW', 'Python', 'ScaFaCoS']:
            dep_flag = 'OFF'
            if get_software_root(dep):
                dep_flag = 'ON'
            self.cfg.update('configopts', f"-DWITH_{dep.upper()}={dep_flag}")
        self.cfg.update('configopts', ' -DWITH_STOKESIAN_DYNAMICS=OFF')
        self.cfg.update('configopts', ' -DWITH_TESTS=ON')
        self.cfg.update('configopts', ' -DCMAKE_SKIP_RPATH=OFF')
        # make sure the right Python is used (note: -DPython3_EXECUTABLE or -DPython_EXECUTABLE does not work!)
        self.cfg.update('configopts', f' -DPYTHON_EXECUTABLE={get_software_root("Python")}/bin/python')

    def _set_configure_options_release_500(self):
        """
        Internal helper function to set configure options for ESPResSo v5.0+.
        """
        cpu_features = get_cpu_features()
        for dep in ['CUDA', 'GSL', 'FFTW', 'Python', 'ScaFaCoS', 'HDF5', 'NLopt']:
            dep_flag = 'OFF'
            if get_software_root(dep):
                dep_flag = 'ON'
            self.cfg.update('configopts', f"-DESPRESSO_BUILD_WITH_{dep.upper()}={dep_flag}")

        version = self._get_version()
        if version != 'commit' and version[:2] < (5, 1) and get_software_root('Kokkos') and get_software_root('Cabana'):
            self.cfg.update('configopts', ' -DESPRESSO_BUILD_WITH_SHARED_MEMORY_PARALLELISM=ON')

        self.cfg.update('configopts', ' -DESPRESSO_BUILD_WITH_STOKESIAN_DYNAMICS=OFF')
        self.cfg.update('configopts', ' -DESPRESSO_BUILD_WITH_WALBERLA=ON')
        if get_cpu_architecture() == X86_64 and 'avx2' in cpu_features:
            self.cfg.update('configopts', ' -DESPRESSO_BUILD_WITH_WALBERLA_AVX=ON')
        self.cfg.update('configopts', ' -DESPRESSO_BUILD_TESTS=ON')
        self._set_exe_linker_flags()

        # build_cmd_targets does not work with CMakeNinja, use buildopts instead
        self.cfg['buildopts'] = 'espresso_packaging_dependencies'

    def configure_step(self):
        """
        Custom configure step for ESPResSo
        """
        # patch FetchContent to avoid re-downloading dependencies
        self._patch_fetchcontent()

        version = self._get_version()
        if version == 'commit' or version[:2] >= (5, 0):
            self._set_configure_options_release_500()
        elif version[:2] >= (4, 2):
            self._set_configure_options_release_420()
        else:
            raise EasyBuildError(
                f'EasyBlock {self.__class__.__name__} doesn\'t implement the '
                f'configure step for ESPResSo {self.version}')

        return super(EB_ESPResSo, self).configure_step()

    def test_step(self):
        """
        Custom test step for ESPResSo
        """
        version = self._get_version()
        if version == 'commit' or version[:2] >= (5, 0):
            testopts = self.cfg.get('testopts', '')
            testopts += f' -j{self.cfg.parallel}'
            testopts += f' --resource-spec-file {self.builddir}/easybuild_obj/testsuite/python/resources.json'
            testopts += ' --output-on-failure --no-tests=error'
            self.cfg['testopts'] = testopts

            if self.cfg['runtest'] is None:
                self.cfg['test_cmd'] = 'ctest'
                self.cfg['runtest'] = '-L "unit_test|python_test"'

        return super(EB_ESPResSo, self).test_step()

    def _cleanup_aux_files(self):
        """
        Remove files automatically installed by CMake outside the ESPResSo
        main directory: header files, config files, duplicated shared objects.
        """
        def delete_dir(path):
            if os.path.isdir(path):
                trace_msg('removing directory \'%s\'' % path.replace(f'{self.installdir}/', ''))
                remove_dir(path)

        def delete_file(path):
            if os.path.isfile(path) or os.path.islink(path):
                trace_msg('removing file \'%s\'' % path.replace(f'{self.installdir}/', ''))
                remove_file(path)

        version = self._get_version()
        if version == 'commit' or version[:2] >= (5, 0):
            lib_dir = f'{self.installdir}/lib'
            if os.path.isdir(f'{self.installdir}/lib64'):
                lib_dir = f'{self.installdir}/lib64'
            delete_dir(f'{self.installdir}/include')
            delete_dir(f'{self.installdir}/share')
            delete_dir(f'{self.installdir}/walberla')
            delete_dir(f'{lib_dir}/cmake')
            for path in os.listdir(lib_dir):
                if '.so' in path:
                    delete_file(f'{lib_dir}/{path}')

    def post_processing_step(self):
        """
        Custom post-processing step for ESPResSo: clean up some auxilary files
        """
        try:
            self._cleanup_aux_files()
        except Exception as err:
            error_msg = "Failed to remove some auxiliary files "
            error_msg = f"(easyblock: {self.__class__.__name__}): {err}"
            raise EasyBuildError(error_msg)
        return super(EB_ESPResSo, self).post_processing_step()

    def sanity_check_step(self):
        """
        Custom sanity check step for ESPResSo
        """
        version = self._get_version()

        # libraries
        if version == 'commit' or version[:2] >= (5, 0):
            _libs = [
                'espresso_core', 'espresso_shapes', 'espresso_walberla',
                'espresso_script_interface', 'script_interface', 'utils', '_init',
            ]
        else:
            _libs = [
                'Espresso_config', 'Espresso_core', 'Espresso_script_interface',
                'Espresso_shapes', '_init', 'analyze', 'code_info', 'electrokinetics',
                'galilei', 'integrate', 'interactions', 'lb', 'particle_data', 'polymer',
                'profiler', 'script_interface', 'system', 'thermostat', 'utils', 'version',
            ]

        # Python modules
        _python_modules = [
            '__init__.py', 'collision_detection.py', 'accumulators.py',
            'constraints.py', 'electrostatics.py', 'magnetostatics.py',
            'observables.py', 'reaction_methods.py',
        ]
        if version == 'commit' or version[:2] >= (5, 0):
            _extra_python_modules = [
                'electrokinetics.py', 'lb.py', 'lees_edwards.py',
                'particle_data.py', 'system.py', 'thermostat.py', 'version.py',
            ]
            _python_modules = sorted(_python_modules + _extra_python_modules)

        if get_software_root('HDF5'):
            if version == 'commit' or version[:2] >= (5, 0):
                _libs.append('espresso_hdf5')
            _python_modules.append(os.path.join('io', 'writer', 'h5md.py'))
        if get_software_root('CUDA'):
            if version == 'commit' or version[:2] >= (5, 0):
                _python_modules.append('cuda_init.py')
            else:
                _libs.append('cuda_init')

        # binaries
        _binaries = ['ipypresso',  'pypresso']

        # Python package directory
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        _lib_path = f'lib/python{pyshortver}/site-packages/espressomd'

        files = [f'bin/{x}' for x in _binaries]
        files += [f'{_lib_path}/{x}.{get_shared_lib_ext()}' for x in _libs]
        files += [f'{_lib_path}/{x}' for x in _python_modules]
        custom_paths = {
            'files': files,
            'dirs': [],
        }
        custom_commands = [
            "pypresso -h",
            "ipypresso -h",
            'pypresso -c "import espressomd.version;print(espressomd.version.friendly())"',
            'python3 -c "import espressomd.version;print(espressomd.version.friendly())"',
        ]

        # call out to parent to do the actual sanity checking, pass through custom paths
        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
