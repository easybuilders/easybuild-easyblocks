##
# Copyright 2021-2024 Vrije Universiteit Brussel
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
EasyBuild support for ORCA, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import glob
import os

from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import write_file
from easybuild.tools.py2vs3 import string_type
from easybuild.tools.systemtools import X86_64, get_cpu_architecture


class EB_ORCA(PackedBinary, MakeCp):
    """
    ORCA installation files are extracted and placed in standard locations using 'files_to_copy' from MakeCp.
    Sanity checks on files are automatically generated based on the contents of 'files_to_copy' by gathering
    the target files in the build directory and checking their presence in the installation directory.
    Sanity checks also include a quick test calculating the HF energy of a water molecule.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters for ORCA."""
        extra_vars = MakeCp.extra_options()
        extra_vars.update(PackedBinary.extra_options())

        # files_to_copy is not mandatory here, since we set it by default in install_step
        extra_vars['files_to_copy'][2] = CUSTOM

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Init and validate easyconfig parameters and system architecture"""
        super(EB_ORCA, self).__init__(*args, **kwargs)

        # If user overwrites 'files_to_copy', custom 'sanity_check_paths' must be present
        if self.cfg['files_to_copy'] and not self.cfg['sanity_check_paths']:
            raise EasyBuildError("Found 'files_to_copy' option in easyconfig without 'sanity_check_paths'")

        # Add orcaarch template for supported architectures
        myarch = get_cpu_architecture()
        if myarch == X86_64:
            orcaarch = 'x86-64'
        else:
            raise EasyBuildError("Architecture %s is not supported by ORCA on EasyBuild", myarch)

        self.cfg.template_values['orcaarch'] = orcaarch
        self.cfg.generate_template_values()

    def install_step(self):
        """Install ORCA with MakeCp easyblock"""

        if not self.cfg['files_to_copy']:
            # Put installation files in standard locations
            files_to_copy = [
                (['auto*', 'orca*', 'otool*'], 'bin'),
                (['*.pdf'], 'share'),
            ]
            # Version 5 extra files
            if LooseVersion(self.version) >= LooseVersion('5.0.0'):
                compoundmethods = (['ORCACompoundMethods'], 'bin')
                files_to_copy.append(compoundmethods)
            # Shared builds have additional libraries
            libs_to_copy = (['liborca*'], 'lib')
            if all([glob.glob(p) for p in libs_to_copy[0]]):
                files_to_copy.append(libs_to_copy)

            self.cfg['files_to_copy'] = files_to_copy

        MakeCp.install_step(self)

    def sanity_check_step(self):
        """Custom sanity check for ORCA"""
        custom_paths = None

        if not self.cfg['sanity_check_paths']:
            custom_paths = {'files': [], 'dirs': []}

            if self.cfg['files_to_copy']:
                # Convert 'files_to_copy' to list of files in build directory
                for spec in self.cfg['files_to_copy']:
                    if isinstance(spec, tuple):
                        file_pattern = spec[0]
                        dest_dir = spec[1]
                    elif isinstance(spec, string_type):
                        file_pattern = spec
                        dest_dir = ''
                    else:
                        raise EasyBuildError(
                            "Found neither string nor tuple as file to copy: '%s' (type %s)", spec, type(spec)
                        )

                    if isinstance(file_pattern, string_type):
                        file_pattern = [file_pattern]

                    source_files = []
                    for pattern in file_pattern:
                        source_files.extend(glob.glob(pattern))

                    # Add files to custom sanity checks
                    for source in source_files:
                        if os.path.isfile(source):
                            custom_paths['files'].append(os.path.join(dest_dir, source))
                        else:
                            custom_paths['dirs'].append(os.path.join(dest_dir, source))
            else:
                # Minimal check of files (needed by --module-only)
                custom_paths['files'] = ['bin/orca']

        # Simple test: HF energy of water molecule
        test_input_content = """
!HF DEF2-SVP
%%PAL NPROCS %(nprocs)s END
* xyz 0 1
O   0.0000   0.0000   0.0626
H  -0.7920   0.0000  -0.4973
H   0.7920   0.0000  -0.4973
*
"""
        nprocs = self.cfg.get('parallel', 1)
        test_input_content = test_input_content % {'nprocs': nprocs}
        test_input_path = os.path.join(self.builddir, 'eb_test_hf_water.inp')
        write_file(test_input_path, test_input_content)

        # Reference total energy
        test_output_energy = '-75.95934031'
        test_output_regex = 'FINAL SINGLE POINT ENERGY[ \t]*%s' % test_output_energy

        # Instruct openmpi to treat hardware threads as slot
        test_ompi_env = 'env OMPI_MCA_hwloc_base_use_hwthreads_as_cpus=1'

        # ORCA has to be executed using its full path to run in parallel
        if os.path.isdir(os.path.join(self.installdir, 'bin')):
            orca_bin = '$EBROOTORCA/bin/orca'
        else:
            orca_bin = '$(which orca)'

        test_orca_cmd = "%s %s %s" % (test_ompi_env, orca_bin, test_input_path)

        custom_commands = [
            # Execute test in ORCA
            test_orca_cmd,
            # Repeat test and check total energy
            "%s | grep -c '%s'" % (test_orca_cmd, test_output_regex),
        ]

        super(EB_ORCA, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
