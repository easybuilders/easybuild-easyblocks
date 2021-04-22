##
# Copyright 2009-2021 Ghent University
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
EasyBuild support for building and installing R packages, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
@author: Balazs Hajgato (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.r import EXTS_FILTER_R_PACKAGES, EB_R
from easybuild.easyblocks.generic.configuremake import check_config_guess, obtain_config_guess
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir, copy_file
from easybuild.tools.run import run_cmd, parse_log_for_error


def make_R_install_option(opt, values, cmdline=False):
    """
    Make option list for install.packages, to specify in R environment.
    """
    txt = ""
    if values:
        if cmdline:
            txt = " --%s=\"%s" % (opt, values[0])
        else:
            txt = "%s=c(\"%s" % (opt, values[0])
        for i in values[1:]:
            txt += " %s" % i
        if cmdline:
            txt += "\""
        else:
            txt += "\")"
    return txt


class RPackage(ExtensionEasyBlock):
    """
    Install an R package as a separate module, or as an extension.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to RPackage."""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'exts_subdir': ['', "Subdirectory where R extensions should be installed info", CUSTOM],
            'unpack_sources': [False, "Unpack sources before installation", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initliaze RPackage-specific class variables."""

        super(RPackage, self).__init__(*args, **kwargs)

        self.configurevars = []
        self.configureargs = []
        self.ext_src = None

    def make_r_cmd(self, prefix=None):
        """Create a command to run in R to install an R package."""
        confvars = "confvars"
        confargs = "confargs"
        confvarslist = make_R_install_option(confvars, self.configurevars)
        confargslist = make_R_install_option(confargs, self.configureargs)
        confvarsstr = ""
        if confvarslist:
            confvarslist = confvarslist + "; names(%s)=\"%s\"" % (confvars, self.name)
            confvarsstr = ", configure.vars=%s" % confvars
        confargsstr = ""
        if confargslist:
            confargslist = confargslist + "; names(%s)=\"%s\"" % (confargs, self.name)
            confargsstr = ", configure.args=%s" % confargs

        if prefix:
            prefix = '"%s", ' % prefix
        else:
            prefix = ''

        r_cmd = """
        options(repos=c(CRAN="http://www.freestatistics.org/cran"))
        %s
        %s
        install.packages("%s", %s dependencies = FALSE %s%s)
        """ % (confvarslist, confargslist, self.name, prefix, confvarsstr, confargsstr)
        cmd = "%s R -q --no-save %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])

        self.log.debug("make_r_cmd returns %s with input %s" % (cmd, r_cmd))

        return (cmd, r_cmd)

    def make_cmdline_cmd(self, prefix=None):
        """Create a command line to install an R package."""
        confvars = ""
        if self.configurevars:
            confvars = make_R_install_option("configure-vars", self.configurevars, cmdline=True)
        confargs = ""
        if self.configureargs:
            confargs = make_R_install_option("configure-args", self.configureargs, cmdline=True)

        if prefix:
            prefix = '--library=%s' % prefix
        else:
            prefix = ''

        if self.start_dir:
            loc = os.path.join(self.ext_dir or os.path.sep, self.start_dir)
        else:
            loc = self.ext_dir or self.ext_src

        cmd = ' '.join([
            self.cfg['preinstallopts'],
            "R CMD INSTALL",
            loc,
            confargs,
            confvars,
            prefix,
            '--no-clean-on-error',
            self.cfg['installopts'],
        ])

        self.log.debug("make_cmdline_cmd returns %s" % cmd)
        return cmd, None

    def configure_step(self):
        """No configuration for installing R packages."""
        pass

    def build_step(self):
        """No separate build step for R packages."""
        pass

    def install_R_package(self, cmd, inp=None):
        """Install R package as specified, and check for errors."""

        cmdttdouterr, _ = run_cmd(cmd, log_all=True, simple=False, inp=inp, regexp=False)

        cmderrors = parse_log_for_error(cmdttdouterr, regExp="^ERROR:")
        if cmderrors:
            cmd = "R -q --no-save"
            stdin = """
            remove.library(%s)
            """ % self.name
            # remove package if errors were detected
            # it's possible that some of the dependencies failed, but the package itself was installed
            run_cmd(cmd, log_all=False, log_ok=False, simple=False, inp=stdin, regexp=False)
            raise EasyBuildError("Errors detected during installation of R package %s!", self.name)
        else:
            self.log.debug("R package %s installed succesfully" % self.name)

    def update_config_guess(self, path):
        """Update any config.guess found in specified directory"""
        for config_guess_dir in (root for root, _, files in os.walk(path) if 'config.guess' in files):
            config_guess = os.path.join(config_guess_dir, 'config.guess')
            if not check_config_guess(config_guess):
                updated_config_guess = obtain_config_guess()
                if updated_config_guess:
                    self.log.debug("Replacing outdated %s with more recent %s", config_guess, updated_config_guess)
                    copy_file(updated_config_guess, config_guess)
                else:
                    raise EasyBuildError("Failed to obtain updated config.guess")

    def install_step(self):
        """Install procedure for R packages."""
        # Update config.guess if the package was extracted
        if self.start_dir:
            self.update_config_guess(self.start_dir)
        cmd, stdin = self.make_cmdline_cmd(prefix=os.path.join(self.installdir, self.cfg['exts_subdir']))
        self.install_R_package(cmd, inp=stdin)

    def run(self):
        """Install R package as an extension."""

        # determine location
        if isinstance(self.master, EB_R):
            # extension is being installed as part of an R installation/module
            (out, _) = run_cmd("R RHOME", log_all=True, simple=False)
            rhome = out.strip()
            lib_install_prefix = os.path.join(rhome, 'library')
        else:
            # extension is being installed in a separate installation prefix
            lib_install_prefix = os.path.join(self.installdir, self.cfg['exts_subdir'])
            mkdir(lib_install_prefix, parents=True)

        if self.src:
            super(RPackage, self).run(unpack_src=True)
            self.ext_src = self.src
            self.update_config_guess(self.ext_dir)
            self.log.debug("Installing R package %s version %s." % (self.name, self.version))
            cmd, stdin = self.make_cmdline_cmd(prefix=lib_install_prefix)
        else:
            if self.patches:
                raise EasyBuildError("Cannot patch R package %s as no explicit source is given!", self.name)
            self.log.debug("Installing most recent version of R package %s (source not found)." % self.name)
            cmd, stdin = self.make_r_cmd(prefix=lib_install_prefix)

        self.install_R_package(cmd, inp=stdin)

    def sanity_check_step(self, *args, **kwargs):
        """
        Custom sanity check for R packages
        """
        return super(RPackage, self).sanity_check_step(EXTS_FILTER_R_PACKAGES, *args, **kwargs)

    def make_module_extra(self):
        """Add install path to R_LIBS_SITE"""
        # prepend R_LIBS_SITE with install path
        extra = self.module_generator.prepend_paths("R_LIBS_SITE", [self.cfg['exts_subdir']])
        return super(RPackage, self).make_module_extra(extra)
