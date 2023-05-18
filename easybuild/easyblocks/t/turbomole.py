"""
EasyBuild support for TURBOMOLE,
implemented as an easyblock

@author: Sven Hansen (RWTH Aachen University)
"""

import os
import re
import stat

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.framework.easyblock import read_file
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.config import WARN
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import change_dir, adjust_permissions, apply_regex_substitutions
from easybuild.tools.run import run_cmd


class EB_TURBOMOLE(Tarball):
    """Support for installing TURBOMOLE."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'sysname': [
                None,
                "Override architecture reported by sysname script",
                CUSTOM
            ],
            'para_arch': [
                None,
                "Configure use of parallelized binaries ('mpi' or 'smp' or None)",
                CUSTOM
            ],
            'full_tests': [
                False,
                "Perform all tests (Default: just a few selected ones)",
                CUSTOM
            ],
        }
        return Tarball.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for TURBOMOLE."""
        super(EB_turbomole, self).__init__(*args, **kwargs)
        self.tmolex = None
        self.tmoledir = ""
        self.sysname = ""

    def get_sysname(self):
        """
        Return the sysname for this machine and config.

        Roughly emulates TURBOMOLE's sysname script. The output is needed
        for module-only builds so we cannot rely on the actual script.
        """
        sysname = ""
        if self.cfg['sysname']:
            sysname = self.cfg['sysname']
        else:
            cmd = "grep vendor /proc/cpuinfo"
            (cpuinfo, _) = run_cmd(cmd)
            vendor = re.search(r"Intel|AMD", cpuinfo)
            if not vendor:
                raise EasyBuildError("Could not determine CPU vendor. Try " +
                                     "providing a sysname manually.")
            if vendor.group() == "Intel":
                sysname = "em64t-unknown-linux-gnu"
            elif vendor.group() == "AMD":
                sysname = "x86_64-unknown-linux-gnu"

        if self.cfg['para_arch']:
            sysname += "_" + self.cfg['para_arch']

        return sysname

    def has_tmolex(self):
        """Return whether a TmoleX installer was provided."""
        if self.tmolex is None:
            self.tmolex = any(re.match(r"TmoleX.*bin", src['name'])
                              for src in self.src)
            self.log.info("Found TmoleX installer: " + str(self.tmolex))

        return self.tmolex

    def get_turboroot(self):
        """Get the root of the TURBOMOLE installation

        With TmoleX, TURBOMOLE is installed in its own
        subdirectory
        """
        return "TURBOMOLE" if self.has_tmolex() else ""

    def extract_step(self):
        """Custom extract step to perform in-place changes and prepare tests"""
        if self.cfg['sysname']:
            self.sysname = self.cfg['sysname']
        else:
            self.sysname = self.get_sysname()

        if not self.has_tmolex():
            super(EB_turbomole, self).extract_step()
        else:
            installer = next(src['path'] for src in self.src if
                             re.match(r"TmoleX.*bin", src['name']))
            cmd = ' '.join([installer, '-q', '-dir', self.builddir])

            result = run_cmd(cmd, log_all=True)
            if result[1] != 0:
                raise EasyBuildError("Failed to run TurbomoleX installer.")

    def install_step(self):
        super(EB_turbomole, self).install_step()
        bindir = os.path.join(self.installdir, self.get_turboroot(), 'bin',
                              self.sysname)
        adjust_permissions(bindir, stat.S_IROTH | stat.S_IXOTH, add=True,
                           relative=True, recursive=True)

    def sanity_check_step(self):
        """Custom sanity check for TmoleX and TURBOMOLE."""
        custom_paths = {
            'files': [os.path.join(self.get_turboroot(), 'scripts', 'TTEST')],
            'dirs': [os.path.join(self.get_turboroot(), 'bin', self.sysname)],
        }

        if self.has_tmolex():
            # search a TmoleX binary since the name cannot be deduced
            # reliably for every version
            tmolexdir = os.path.join(self.installdir, "TmoleX")
            tmolex_binary = ""
            files = [file for file in os.listdir(tmolexdir)
                     if os.path.isfile(os.path.join(tmolexdir, file))]
            for file in os.listdir(tmolexdir):
                if os.path.isfile(os.path.join(tmolexdir, file)):
                    match = re.match(r"TmoleX([0-9]+)$", file)
                    if match:
                        tmolex_binary = os.path.join("TmoleX", file)
                        break

            if not tmolex_binary:
                raise EasyBuildError("Could not find TmoleX binary.")

            custom_paths['files'].append(tmolex_binary)

        super(EB_turbomole, self).sanity_check_step(custom_paths=custom_paths)

    def test_step(self):
        """Custom test for TURBOMOLE, based on TTEST script"""
        oldcwd = change_dir(os.path.join(self.builddir, "TURBOMOLE", 'TURBOTEST'))

        turbodir = os.path.join(self.builddir, "TURBOMOLE")
        ttest = os.path.join(turbodir, 'scripts', 'TTEST')

        setvar('TURBODIR', turbodir)
        setvar('TURBOMOLE_SYSNAME', self.sysname)
        if self.cfg['para_arch']:
            setvar('PARA_ARCH', self.cfg['para_arch'])
        os.environ['PATH'] += os.pathsep + os.path.join(self.builddir,
                                                        "TURBOMOLE", "scripts")

        testcmd = ' '.join([ttest, '--errstop', '--short'])
        if self.cfg['para_arch'] == 'smp':
            testcmd += " -o smpparallel"
        elif self.cfg['para_arch'] == 'mpi':
            testcmd += " -o parallel"

        if not self.cfg['full_tests']:
            # restrict the test suite via the DEFCRIT file
            deffile = "./DEFCRIT"
            sub_progs = (r'(\w*)progs => \[.*\]',
                         r'\1progs => [ "dscf", "grad", "ridft" ]')
            apply_regex_substitutions(deffile, [sub_progs], backup=False,
                                      on_missing_match=WARN)
            self.log.debug("DEFCRIT was changed to:\n" + read_file(deffile))

        test_ok = run_cmd(testcmd, log_ok=True, simple=True)
        if not test_ok:
            raise EasyBuildError("TURBOMOLE test returned non-zero exit code.")

        checkcmd = ttest + ' --check'
        test_passed = run_cmd(checkcmd, log_ok=True, simple=True)
        if not test_passed:
            raise EasyBuildError("Test check failed.")

        cleancmd = ttest + ' --realclean'
        cleaned = run_cmd(cleancmd, inp='y\n', log_ok=True, simple=True)
        if not cleaned:
            raise EasyBuildError("Cleaning test directory failed.")

        change_dir(oldcwd)

    def make_module_extra(self):
        """Module preparation for TURBOMOLE and TmoleX"""
        if not self.sysname:
            self.sysname = self.get_sysname()
        bindir = os.path.join(self.get_turboroot(), 'bin', self.sysname)
        tmolescriptdir = os.path.join(self.get_turboroot(), 'scripts')
        execpaths = [bindir, tmolescriptdir]

        if self.has_tmolex():
            execpaths.append('TmoleX')
            self.cfg['description'] += "\n\n This module contains the TmoleX GUI."

        txt = super(Tarball, self).make_module_extra()
        txt += self.module_generator.set_environment('TURBODIR',
                                                     self.get_turboroot(),
                                                     relpath=True)
        if self.cfg['para_arch']:
            txt += self.module_generator.set_environment('PARA_ARCH',
                                                         self.cfg['para_arch'])

        txt += self.module_generator.prepend_paths('PATH', execpaths)
        return txt
