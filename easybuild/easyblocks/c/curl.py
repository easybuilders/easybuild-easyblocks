##
# Copyright 2026 Ghent University
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
EasyBuild support for building and installing cURL, implemented as an easyblock

When EasyBuild is configured with --sysroot, cURL is pointed at the CA bundle in that
sysroot (the compat-layer store used by EESSI) instead of a path detected on the build host.

Easyconfigs pick this up by leaving ``easyblock`` unset (or setting it to ``EB_cURL``).
An explicit ``easyblock = 'ConfigureMake'`` or ``easyblock = 'CMakeMake'`` selects that
generic class instead.

The default build is the autotools ``./configure`` used by current cURL easyconfigs.
Set ``configure_cmd = 'cmake'`` to build with CMake.

@author: Rohit Goswami
"""
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.utilities import trace_msg


# CA bundle shipped by Debian/Ubuntu and by the Gentoo Prefix compat layer used as an EESSI sysroot.
SYSROOT_CA_BUNDLE_RELPATH = os.path.join('etc', 'ssl', 'certs', 'ca-certificates.crt')

# Configure options and CMake cache variables that already select a CA location.
_CA_CONFIGURE_PREFIXES = ('--with-ca-bundle', '--with-ca-path')
_CA_LOCATION_NAMES = ('CURL_CA_BUNDLE', 'CURL_CA_PATH')


def _token_sets_ca_location(token):
    """Return True if a configopts/preconfigopts token already selects a cURL CA bundle or path."""
    if token.startswith(_CA_CONFIGURE_PREFIXES):
        return True
    for name in _CA_LOCATION_NAMES:
        # -DCURL_CA_BUNDLE=..., -DCURL_CA_BUNDLE:STRING=..., CURL_CA_BUNDLE=...
        if f'{name}=' in token or f'{name}:' in token:
            return True
    return False


def _text_sets_ca_location(text):
    """Return True if any shell token in ``text`` already selects a cURL CA bundle or path."""
    if not text:
        return False
    return any(_token_sets_ca_location(token) for token in str(text).split())


def _uses_cmake(configure_cmd):
    """Return True when ``configure_cmd`` invokes CMake rather than ./configure."""
    configure_cmd = (configure_cmd or '').strip()
    if not configure_cmd:
        return False
    return os.path.basename(configure_cmd.split()[0]) == 'cmake'


def det_curl_ca_configopt(sysroot, configopts='', preconfigopts='', configure_cmd='./configure',
                          ca_bundle=None, env_ca_bundle=None, isfile=None):
    """
    Determine the configure/CMake option that selects the sysroot CA bundle.

    An option is returned only when ``sysroot`` is set, the bundle file exists, and the build
    does not already supply ``--with-ca-bundle``, ``--with-ca-path`` or ``CURL_CA_BUNDLE``
    (including ``CURL_CA_PATH``, the CMake form of ``--with-ca-path``).

    :param sysroot: value of the ``--sysroot`` build option, or a false value when unset
    :param configopts: current ``configopts`` value
    :param preconfigopts: current ``preconfigopts`` value
    :param configure_cmd: configure command (``./configure`` or ``cmake``)
    :param ca_bundle: ``ca_bundle`` easyconfig parameter (``None``, ``False`` or an absolute path)
    :param env_ca_bundle: ``CURL_CA_BUNDLE`` environment value, if set
    :param isfile: callable used to test whether the bundle path exists (default: ``os.path.isfile``)
    :return: ``(option, warning, skip_reason)``. ``option`` is appended to ``configopts`` when not
             ``None``. ``warning`` is set when the default sysroot bundle is missing.
             ``skip_reason`` is an informational message when a user setting suppresses the option.
    """
    if isfile is None:
        isfile = os.path.isfile

    if ca_bundle is not None and ca_bundle is not False and not isinstance(ca_bundle, str):
        raise EasyBuildError(f"Invalid ca_bundle value {ca_bundle!r}: expected None, False or an absolute path")

    if not sysroot:
        if isinstance(ca_bundle, str) and ca_bundle.strip():
            return None, None, "ca_bundle is set but --sysroot is not; not adding a cURL CA bundle option"
        return None, None, None

    if _text_sets_ca_location(configopts) or _text_sets_ca_location(preconfigopts) or env_ca_bundle:
        return None, None, "CA bundle or path already specified; not overriding it"

    if ca_bundle is False:
        return None, None, "ca_bundle=False; not adding a cURL CA bundle option"

    explicit = isinstance(ca_bundle, str)
    if explicit:
        ca_bundle = ca_bundle.strip()
        if not ca_bundle:
            raise EasyBuildError("ca_bundle must be an absolute path, False, or unset (got an empty value)")
        if not os.path.isabs(ca_bundle):
            raise EasyBuildError(f"ca_bundle must be an absolute path: {ca_bundle}")
        bundle_path = ca_bundle
    else:
        bundle_path = os.path.join(sysroot, SYSROOT_CA_BUNDLE_RELPATH)

    if not isfile(bundle_path):
        if explicit:
            raise EasyBuildError(f"Specified ca_bundle does not exist: {bundle_path}")
        warning = (f"CA bundle {bundle_path} was not found under sysroot {sysroot}; "
                   "cURL will not be configured with a CA bundle from the sysroot")
        return None, warning, None

    flag = '-DCURL_CA_BUNDLE=' if _uses_cmake(configure_cmd) else '--with-ca-bundle='
    return flag + bundle_path, None, None


class EB_cURL(CMakeMake):
    """
    Support for building and installing cURL.

    Subclasses CMakeMake (itself a ConfigureMake) so one easyblock can drive the autotools
    build used by current easyconfigs and a CMake build (``configure_cmd = 'cmake'``).
    The default configure command remains ``./configure``.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Custom easyconfig parameters for cURL."""
        extra_vars = CMakeMake.extra_options(extra_vars)
        # CMakeMake defaults configure_cmd to 'cmake'. cURL easyconfigs use the configure script.
        extra_vars['configure_cmd'] = [
            './configure',
            "Configure command to use. Set to 'cmake' to build cURL with CMake.",
            CUSTOM,
        ]
        # CMakeMake redefines build_type as the CMake build type. Keep the ConfigureMake meaning
        # for the default autotools build, and describe the CMake meaning as well.
        extra_vars['build_type'] = [
            None,
            "For ./configure: value of --build (for example x86_64-pc-linux-gnu). "
            "None uses config.guess, False leaves it to the configure script. "
            "For configure_cmd = 'cmake': CMake build type (Release, RelWithDebInfo or Debug); "
            "None then follows toolchainopts[debug,noopt].",
            CUSTOM,
        ]
        extra_vars['ca_bundle'] = [
            None,
            "CA bundle to build into cURL when --sysroot is set. "
            "None uses <sysroot>/etc/ssl/certs/ca-certificates.crt when that file exists, "
            "False disables it, or pass an absolute path to a bundle file. "
            "Ignored when --sysroot is not set. "
            "Also ignored when configopts, preconfigopts or $CURL_CA_BUNDLE already select "
            "a CA bundle or path (--with-ca-bundle, --with-ca-path, CURL_CA_BUNDLE, CURL_CA_PATH).",
            CUSTOM,
        ]
        return extra_vars

    def _uses_cmake(self):
        """Return True if this cURL build is configured with CMake."""
        return _uses_cmake(self.cfg.get('configure_cmd'))

    def _add_sysroot_ca_bundle(self):
        """Append the sysroot CA bundle option to configopts when that is appropriate."""
        option, warning, skip_reason = det_curl_ca_configopt(
            sysroot=build_option('sysroot'),
            configopts=self.cfg['configopts'],
            preconfigopts=self.cfg['preconfigopts'],
            configure_cmd=self.cfg.get('configure_cmd'),
            # .get so a ConfigureMake easyconfig passed via --easyblock=EB_cURL still works:
            # that config was parsed before this easyblock's parameters were known.
            ca_bundle=self.cfg.get('ca_bundle'),
            env_ca_bundle=(os.environ.get('CURL_CA_BUNDLE') or '').strip() or None,
        )
        if warning:
            print_warning(warning, log=self.log)
        if skip_reason:
            self.log.info(skip_reason)
        if option:
            self.log.info("Configuring cURL to use CA bundle via %s", option)
            trace_msg(f"cURL CA bundle: {option}")
            self.cfg.update('configopts', option)

    def _prepare_cmake_configure_cmd(self):
        """
        CMakeMake applies its CMake options only when configure_cmd is exactly 'cmake'.
        Fold a custom cmake path or trailing arguments into that form.
        """
        tokens = self.cfg['configure_cmd'].split()
        if not tokens or tokens == ['cmake']:
            return
        if len(tokens) > 1:
            extra = ' '.join(tokens[1:])
            self.log.info("Moving extra arguments from configure_cmd into configopts: %s", extra)
            self.cfg.update('configopts', extra)
        self.log.info("Normalising configure_cmd %s to 'cmake' for CMakeMake", tokens[0])
        self.cfg['configure_cmd'] = 'cmake'

    def configure_step(self, *args, **kwargs):
        """Configure cURL, selecting the sysroot CA bundle when --sysroot is set."""
        self._add_sysroot_ca_bundle()
        if self._uses_cmake():
            self._prepare_cmake_configure_cmd()
            return CMakeMake.configure_step(self, *args, **kwargs)
        return ConfigureMake.configure_step(self, *args, **kwargs)

    def test_step(self):
        """Use CTest for CMake builds and the Make test step for autotools builds."""
        if self._uses_cmake():
            return CMakeMake.test_step(self)
        return ConfigureMake.test_step(self)
