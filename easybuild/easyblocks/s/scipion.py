##
# Copyright 2015-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for building and installing Scipion, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
from distutils.version import LooseVersion
import fileinput
import os
import re
import sys

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file, which
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd


class EB_Scipion(EasyBlock):
    """Support for building/installing Scipion."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Scipion."""
        super(EB_Scipion, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Scipion."""
        extra_vars = {
            #'mandatory_extra_param': ['default value', "short description", MANDATORY],
            'optional_extra_param': ['default value', "short description", CUSTOM],
         }
        return EasyBlock.extra_options(extra_vars)

    def extract_step(self):
        """Extract Scipion sources."""
        # strip off 'scipion-*' part to avoid having everything in a subdirectory
        self.cfg.update('unpack_options', '--strip-components=1')
        super(EB_Scipion, self).extract_step()

    def configure_step(self):
        """Custom configuration procedure for Scipion."""
        run_cmd("./scipion config")

        # patch scipion.cfg file
        cfgfile = os.path.join(self.cfg['start_dir'], 'config', 'scipion.conf')

        params = {
            'CC': os.environ['CC'],
            'CXX': os.environ['CXX'],
            'LINKERFORPROGRAMS': os.environ['CXX'],
            'MPI_LINKERFORPROGRAMS': os.environ.get('MPICXX', 'UNKNOWN'),
        }

        deps = [
            # dep name, is required dep
            ('frealign', 'FREALIGN_HOME', False),
            ('Java', 'JAVA_HOME', True),
            ('RELION', 'RELION_HOME', False),
            ('SPIDER', 'SPIDER_DIR', False),
            ('Xmipp', 'XMIPP_HOME', True),
        ]
        if get_software_root('ctffind'):
            # note: check whether ctffind 4.x is being used
            if LooseVersion(get_software_version('ctffind')).version[0] == 4:
                deps.append(('ctffind', 'CTFFIND4_HOME', False))
            else:
                deps.append(('ctffind', 'CTFFIND_HOME', False))

        missing_deps = []
        for dep, var, required in deps:
            root = get_software_root(dep)
            if root:
                params.update({var: root})
            elif required:
                missing_deps.append(dep)

            # special treatment, also set 'SPIDER' variable to indicate name of binary
            if dep == 'SPIDER':
                params.update({var: "%s/spider\nSPIDER = %s" % (root, which('spider'))})

        if missing_deps:
            raise EasyBuildError("One or more required dependencies not available: %s", ', '.join(missing_deps))

        for line in fileinput.input(cfgfile, inplace=1, backup='.orig'):
            for (key, val) in params.items():
                line = re.sub(r"^(%s\s*=\s*).*$" % key, r"\1 %s" % val, line)
            sys.stdout.write(line)

        self.log.debug("%s: %s", cfgfile, read_file(cfgfile))

    def build_step(self):
        """Custom build (and install) procedure for Scipion."""
        extra_opts = '--no-opencv --no-scipy'  # --no-xmipp'
        run_cmd("./scipion install -j %s %s" % (self.cfg['parallel'], extra_opts))

    def test_step(self):
        """Custom built-in test procedure for Scipion."""
        # see http://scipion.cnb.csic.es/bin/view/TWiki/RunningTests

        fake_mod_data = self.load_fake_module(purge=True)

        small_tests = [
            # classes and functions, using simulated dataset of Worm Hemogoblin with 76 images (~50s)
            'model.test_object',
            'model.test_mappers',
            'em.data.test_data',
            'em.data.test_convert_xmipp',
            # spider MDA Workflow, using fake dataset of Worm Hemogoblin with 76 images (~50s)
            #'em.workflows.test_workflow_spiderMDA',  # FIXME: reenable
            # EMX import, using the different data sets used in http://i2pc.cnb.csic.es/em (~10s)
            'tests.em.protocols.test_protocols_emx',
            # CTF Discrepancy, using CTF obtained from micrograph of PcV (~10s)
            'tests.em.workflows.test_workflow_xmipp_ctf_discrepancy.TestXmippCTFDiscrepancyBase',
        ]
        medium_tests = [
            # Xmipp Workflow, using dataset with 3 micrographs of the Bovino Papiloma Virus (BPV)
            'em.workflows.test_workflow_xmipp',
            # Mixed Workflow 3D Reconstruction, same data as in Xmipp Workflow;
            # a refined volume generated with Frealign is obtained
            'em.workflows.test_workflow_mixed.TestMixedBPV',
            # Mixed Workflow Initial Volume, same data as in Xmipp Workflow;
            # an initial volume generated with EMAN is obtained
            'em.workflows.test_workflow_mixed.TestMixedBPV2',
        ]
        for test in small_tests + medium_tests:
            run_cmd("scipion tests %s" % test)

        self.clean_up_fake_module(fake_mod_data)

    def install_step(self):
        """No custom install(-only) procedure for Scipion."""
        pass

    def sanity_check_step(self):
        """Custom sanity check for Scipion."""
        custom_paths = {
            'files': ['scipion'],
            'dirs': ['scripts'],
        }
        super(EB_Scipion, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for Scipion."""
        guesses = super(EB_Scipion, self).make_module_req_guess()
        guesses.update({
            'PATH': ['.', 'scripts'],
        })
        return guesses
