##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for building and installing scipy, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.fortranpythonpackage import FortranPythonPackage
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.easyblocks.numpy import parse_numpy_test_suite_output
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
import easybuild.tools.toolchain as toolchain


class EB_scipy(FortranPythonPackage):
    """Support for installing the scipy Python package as part of a Python installation."""

    @staticmethod
    def extra_options():
        """Easyconfig parameters specific to scipy."""
        extra_vars = ({
            'ignore_test_failures': [True, "Ignore test failures/errors in test suite.", CUSTOM],
        })
        return FortranPythonPackage.extra_options(extra_vars=extra_vars)

    def __init__(self, *args, **kwargs):
        """Set scipy-specific test command."""
        super(EB_scipy, self).__init__(*args, **kwargs)

        self.testinstall = True
        # LDFLAGS should not be set when testing numpy/scipy, because it overwrites whatever numpy/scipy sets
        # see http://projects.scipy.org/numpy/ticket/182
        self.testcmd = "unset LDFLAGS && cd .. && %(python)s -c 'import numpy; import scipy; scipy.test(verbose=2)'"

    def configure_step(self):
        """Custom configure step for scipy: set extra installation options when needed."""
        super(EB_scipy, self).configure_step()

        if LooseVersion(self.version) >= LooseVersion('0.13'):
            # in recent scipy versions, additional compilation is done in the install step,
            # which requires unsetting $LDFLAGS
            if self.toolchain.comp_family() in [toolchain.GCC, toolchain.CLANGGCC]:  # @UndefinedVariable
                self.cfg.update('preinstallopts', "unset LDFLAGS && ")

    def test_step(self):
        """Run available scipy unit tests"""
        if self.cfg['runtest']:
            # Let's handle the output from the scipy test suite ourselves
            testcmd_output, testcmd_exit_code = super(EB_scipy, self).test_step(return_testcmd_output=True)
            testsuite_summary = parse_numpy_test_suite_output(testcmd_output)

            if testsuite_summary and ('failed' in testsuite_summary or 'error' in testsuite_summary):
                failure_text = "Found errors or failures in scipy testsuite output:\n %s" % testsuite_summary
                if self.cfg['ignore_test_failures']:
                    self.log.warning("Ignoring: ", failure_text)
                    print_warning("Ignoring: %s" % failure_text)
                else:
                    raise EasyBuildError(failure_text)

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for scipy."""

        # can't use self.pylibdir here, need to determine path on the fly using currently active 'python' command;
        # this is important for numpy installations for multiple Python version (via multi_deps)
        custom_paths = {
            'files': [],
            'dirs': [det_pylibdir()],
        }

        return super(EB_scipy, self).sanity_check_step(custom_paths=custom_paths)
