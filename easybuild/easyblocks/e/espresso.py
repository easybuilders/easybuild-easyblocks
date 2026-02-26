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
from easybuild.tools.systemtools import get_cpu_architecture, get_cpu_features
from easybuild.tools.systemtools import X86_64
from easybuild.tools.utilities import trace_msg
from easybuild.tools.build_log import print_error
from easybuild.tools.filetools import remove_file, remove_dir
from easybuild.tools import LooseVersion


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
            if not tarball.endswith('.tar.gz'):
                raise ValueError(tarball + ' is not a tar.gz file')
            prefix = tarball.rsplit('.', 2)[0]
            matches = [x for x in os.listdir(src['finalpath']) if x.startswith(prefix)]
            if len(matches) == 0:
                raise RuntimeError(tarball + ' was not extracted')
            if len(matches) > 1:
                raise RuntimeError(tarball + ' matches multiple folders: ' + str(matches))
            extracted_paths[name] = os.path.join(src['finalpath'], matches[0])
        return extracted_paths

    def _patch_fetchcontent(self):
        """
        Modify CMake ``FetchContent_Declare`` blocks to point to the folders
        containing the already-downloaded dependencies rather than to URLs.
        This avoids a download step during configuration.
        """
        extracted_paths = self._get_extracted_tarball_paths()
        cmakelists_path = os.path.join(extracted_paths['espresso'], 'CMakeLists.txt')
        with open(cmakelists_path, 'r') as f:
            content = f.read()
        for name, local_uri in extracted_paths.items():
            if name == 'espresso':
                continue
            pattern = fr'FetchContent_Declare\(\s*{name}\s+GIT_REPOSITORY\s+\S+\s+GIT_TAG\s+\S+(?=\s|\))'
            m = re.search(pattern, content, flags=re.IGNORECASE)
            if m is None:
                raise RuntimeError(f'{name} is not part of the ESPResSo FetchContent workflow')
            content = re.sub(pattern, f'FetchContent_Declare({name} URL {local_uri}', content, flags=re.IGNORECASE)
        with open(cmakelists_path, 'w') as f:
            f.write(content)

    def _get_version(self):
        if '.' in self.version:
            version = tuple(LooseVersion(self.version).version)
        else:
            version = 'commit'
        return version

    def _configure_step_release_420(self):
        configopts = self.cfg.get('configopts', '')
        dependencies = self.cfg.dependencies()
        dependencies_names = {x.get('name', '') for x in dependencies}

        def cmake_if_has(name):
            return 'ON' if name in dependencies_names else 'OFF'

        configopts += f' -DWITH_CUDA={cmake_if_has("CUDA")}'
        configopts += f' -DWITH_GSL={cmake_if_has("GSL")}'
        configopts += ' -DWITH_FFTW=ON'
        configopts += ' -DWITH_PYTHON=ON'
        configopts += ' -DWITH_SCAFACOS=OFF'
        configopts += ' -DWITH_STOKESIAN_DYNAMICS=OFF'
        configopts += ' -DWITH_TESTS=ON'

        self.cfg['configopts'] = configopts

    def _configure_step_release_500(self):
        configopts = self.cfg.get('configopts', '')
        dependencies = self.cfg.dependencies()
        dependencies_names = {x.get('name', '') for x in dependencies}

        def cmake_if_has(name):
            return 'ON' if name in dependencies_names else 'OFF'

        cpu_features = get_cpu_features()

        configopts += f' -DESPRESSO_BUILD_WITH_CUDA={cmake_if_has("CUDA")}'
        configopts += f' -DESPRESSO_BUILD_WITH_HDF5={cmake_if_has("HDF5")}'
        configopts += f' -DESPRESSO_BUILD_WITH_GSL={cmake_if_has("GSL")}'
        configopts += f' -DESPRESSO_BUILD_WITH_NLOPT={cmake_if_has("NLopt")}'
        configopts += ' -DESPRESSO_BUILD_WITH_SHARED_MEMORY_PARALLELISM=ON'
        configopts += ' -DESPRESSO_BUILD_WITH_WALBERLA=ON'
        if get_cpu_architecture() == X86_64 and 'avx2' in cpu_features:
            configopts += ' -DESPRESSO_BUILD_WITH_WALBERLA_AVX=ON'
        configopts += ' -DESPRESSO_BUILD_WITH_FFTW=ON'
        configopts += ' -DESPRESSO_BUILD_WITH_PYTHON=ON'
        configopts += ' -DESPRESSO_BUILD_WITH_SCAFACOS=OFF'
        configopts += ' -DESPRESSO_BUILD_WITH_STOKESIAN_DYNAMICS=OFF'
        configopts += ' -DESPRESSO_BUILD_TESTS=ON '

        self.cfg['configopts'] = configopts

    def configure_step(self):
        # patch FetchContent to avoid re-downloading dependencies
        self._patch_fetchcontent()

        version = self._get_version()
        if version == 'commit':
            self._configure_step_release_500()
        elif version[:2] >= (5, 0):
            self._configure_step_release_500()
        elif version[:2] >= (4, 2):
            self._configure_step_release_420()
        else:
            raise NotImplementedError(
                f'EasyBlock {self.__class__.__name__} doesn\'t implement the '
                f'configure step for ESPResSo {self.version}')

        return super(EB_ESPResSo, self).configure_step()

    def test_step(self):
        version = self._get_version()
        if version == 'commit' or version[:2] >= (5, 0):
            testopts = self.cfg.get('testopts', '')
            testopts += f' -j{self.cfg.parallel}'
            testopts += f' --resource-spec-file {self.builddir}/easybuild_obj/testsuite/python/resources.json'
            self.cfg['testopts'] = testopts

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
        try:
            self._cleanup_aux_files()
        except Exception as err:
            print_error('Failed to remove some auxiliary files '
                        f'(easyblock: {self.__class__.__name__}): {err}')
        return super(EB_ESPResSo, self).post_processing_step()
