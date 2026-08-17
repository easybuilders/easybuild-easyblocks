"""
EasyBuild support for ICON, implemented as an easyblock

@author: Jarne Renders (Vrije Universiteit Brussel)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools import toolchain
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_ICON(ConfigureMake):
    """Support for building/installing ICON."""

    # Dependencies providing the libraries referenced in LIBS, common to every toolchain
    REQUIRED_DEPS = ['libxml2', 'libfyaml', 'ecCodes', 'netCDF', 'netCDF-Fortran']

    def _check_dependencies(self):
        """Make sure the dependencies backing LIBS are actually loaded."""
        for dep_name in self.REQUIRED_DEPS:
            if not get_software_root(dep_name):
                raise EasyBuildError("ICON requires %s as a dependency to link against, but it is not loaded.",
                                     dep_name)

    def _add_model_features(self, comp_fam):
        """Model Features."""
        self.cfg.update('configopts', (
            '--enable-atmo '         # atmosphere component [default=yes]
            '--enable-les '          # Large-Eddy Simulation component [default=yes]
            '--enable-upatmo '       # upper atmosphere component [default=yes]
            '--enable-ocean '        # ocean component [default=yes]
            '--enable-jsbach '       # land component JSBACH [default=yes]
            '--enable-jsbach-hd '    # hydrological discharge scheme of the JSBACH land component [default=auto]
            '--enable-coupling '     # coupling [default=yes]
            '--enable-aes '          # AES physics package [default=yes]
            '--enable-nwp '          # NWP physics package [default=yes]
            '--enable-rte-rrtmgp '   # RTE+RRTMGP toolbox for radiation calculations [default=yes]
            '--enable-art '          # aerosols and reactive trace component ART [default=no]
            '--enable-art-gpl '      # GPL-licensed code parts of the ART component [default=no]
            '--enable-comin '        # ICON community interfaces [default=no]
        ))

        # ecRad requires --enable-openmp, which is mutually exclusive with --enable-gpu
        if comp_fam != toolchain.NVHPC:
            self.cfg.update('configopts', (
                '--enable-waves '    # ocean surface wave component [default=no]
                '--enable-ecrad '    # ECMWF radiation scheme (ECRAD) [default=no]
            ))

        # Not currently used - subject to a license agreement:
        #   '--enable-acm-license '  # accepting ACM Software License Agreement [default=no]
        #   '--enable-rttov '        # radiative transfer model for TOVS [default=no]
        #                            #     https://nwp-saf.eumetsat.int/site/software/rttov/download/#Software
        #   '--enable-dace '         # DACE modules for data assimilation [default=no]
        #                            #     "Data Assimilation Coding Environment (DACE)"
        #                            #     http://www.cosmo-model.org/content/support/software/#dace
        #   '--enable-emvorado '     # radar forward operator EMVORADO [default=no]
        #                            #     "Efficient Modular VOlume scan RADar Operator (EMVORADO)"
        #   '--enable-hd=yes '       # Hydrological Discharge (HD) model [default=no]:
        #                            #     05deg|yes  enable for the 0.5-degree global domain
        #                            #     5min       enable for the 5min global domain
        #                            #     no         disable the HD model

    def _add_infrastructural_features(self, comp_fam):
        """Infrastructural Features."""
        if self.toolchain.mpi_family():
            self.cfg.update('configopts', (
                'MPI_LAUNCH=mpirun '
                '--enable-mpi '              # MPI (parallelization) support [default=yes]
                '--disable-mpi-checks '      # configure-time checks of MPI library [default=yes]
            ))
        else:
            raise EasyBuildError("ICON requires an mpi-enabled toolchain.")

        self.cfg.update('configopts', (
            '--enable-async-io-rma '     # MPI RMA for asynchronous I/O [default=yes]
            '--enable-grib2 '            # GRIB2 I/O [default=no]
            '--enable-parallel-netcdf '  # parallel features of NetCDF [default=no]
            '--enable-cdi-pio '          # parallel features of CDI [default=no]
            '--enable-yaxt '             # YAXT data exchange [default=no]
        ))

        # --enable-openmp is mutually exclusive with --enable-gpu
        if comp_fam == toolchain.NVHPC:
            self.cfg.update('configopts', (
                '--enable-mpi-gpu '   # GPU-aware MPI features [default=no]
                '--enable-gpu=yes '   # GPU support [default=no]: - do not combine with --enable-openmp
                                      #    openacc+cuda  with OpenACC and CUDA
                                      #    openacc+hip   with OpenACC and HIP
                                      #    openacc       alias for 'openacc+cuda'
                                      #    yes           alias for 'openacc+cuda'
                                      #    no            disable GPU support
            ))
        else:
            # OpenMP support [default=no] - do not combine with --enable-gpu
            self.cfg.update('configopts', '--enable-openmp ')

        # Not currently used:
        #   '--enable-active-target-sync '  # MPI active target mode [default=no]
        #   '--enable-mpi-rget '       # MPI_Rget routine [default=auto] - if MPI library supports standard 3.0
        #                                or higher
        #   '--enable-sct '            # SCT timer [default=no]
        #   '--enable-explicit-fpp '   # explicit Fortran preprocessing [default=auto]
        #   '--enable-serialization '  # Serialbox2 serialization [default=no]:
        #                              #    read     enable READ mode
        #                              #    perturb  enable READ & PERTURB mode
        #                              #    create   enable CREATE mode
        #                              #    yes      alias for 'read'
        #                              #    no       disable serialization
        #   '--enable-testbed '        # ICON Testbed infrastructure [default=no]
        #   '--enable-memory-tracing ' # native dynamic memory tracing facility [default=no]:
        #                              #    mtrace  enable tracing with mtrace (glibc)
        #                              #    yes     alias for 'mtrace'
        #                              #    no      disable memory tracing

    def _add_optimization_features(self, comp_fam):
        """Optimization Features."""
        self.cfg.update('configopts', (
            '--enable-vectorized-lrtm '      # parallelization-invariant version of LRTM [default=no]
            '--enable-fcgroup-OCEAN=src/hamocc:src/ocean:src/sea_ice '
        ))

        if comp_fam == toolchain.NVHPC:
            self.cfg.update('configopts', (
                '--enable-dim-swap '      # dimension swap [default=auto]
                '--enable-cuda-graphs '   # CUDA graphs [default=no]
            ))

        # Not currently used:
        #   '--enable-loop-exchange '      # loop exchange [default=auto] - enabled if no GPU support requested
        #   '--enable-realloc-buf '        # reallocatable buffer in the communication [default=no]
        #   '--enable-mixed-precision '    # mixed precision dycore [default=no]
        #   '--enable-intel-consistency '  # Intel compiler directives enforcing consistency [default=auto]
        #   '--enable-pgi-inlib '          # PGI/NVIDIA cross-file function inlining via an inline library
        #                                    [default=no]
        #   '--enable-nccl '               # NCCL for communication [default=no]
        #   '--enable-fcgroup-<NAME> '     # Fortran compile group <NAME> for extra set of compiler flags

    # Maps each --with-external-<name> option to EasyBuild dependency
    # If eb dependency is not provided, it is built from a git submodule (if enabled)
    EXTERNAL_LIBS = {
        'tixi': 'TIXI',               # https://gitlab.dkrz.de/icon-libraries/libtixi
        'yac': 'YAC',                 # https://gitlab.dkrz.de/dkrz-sw/yac
        'mtime': 'libmtime',          # https://gitlab.dkrz.de/icon-libraries/libmtime
        'cdi': 'CDI',                 # https://code.mpimet.mpg.de/projects/cdi/
        'ppm': 'ScalES-PPM',          # https://gitlab.dkrz.de/jahns/ppm
        'yaxt': 'yaxt',               # https://gitlab.dkrz.de/dkrz-sw/yaxt
        'sct': 'SCT',                 # https://gitlab.dkrz.de/dkrz-sw/sct
        'ecrad': 'ecRad',             # https://confluence.ecmwf.int/display/ECRAD/ECMWF+Radiation+Scheme+Home
        'rte-rrtmgp': 'RTE-RRTMGP',   # https://github.com/earth-system-radiation/rte-rrtmgp
    }

    def _add_external_libraries(self):
        """External Libraries: linked against instead of the bundled submodule if loaded as a dependency."""
        for opt_name, dep_name in self.EXTERNAL_LIBS.items():
            if get_software_root(dep_name):
                self.cfg.update('configopts', f'--with-external-{opt_name}')

    def _add_compiler_flags(self, comp_fam):
        """Toolchain-specific compiler flags (FCFLAGS, CFLAGS, LIBS, ...)."""
        # LIBS is identical for foss and intel (no CUDA libraries, both need
        # -Wl,--disable-new-dtags); NVHPC's differs (own -Wl,... prefix, adds CUDA libs).
        gcc_libs = (
            'LIBS="'
            '    -Wl,--disable-new-dtags -Wl,--as-needed'
            '    -lxml2'
            '    -lfyaml'
            '    -leccodes_f90 -leccodes'
            '    $LIBLAPACK'
            '    -lnetcdff -lnetcdf'
            '    -lstdc++'
            '"'
        )
        intel_libs = gcc_libs
        nvhpc_libs = (
            'LIBS="'
            '    -Wl,--as-needed'
            '    -lxml2'
            '    -lfyaml'
            '    -leccodes_f90 -leccodes'
            '    $LIBLAPACK'
            '    -lnetcdff -lnetcdf'
            '    -lcudart -lcuda'
            '    -lstdc++'
            '"'
        )

        if comp_fam == toolchain.NVHPC:
            # Following config/mpim/bullseye.gpu.nvhpc and config/dkrz/levante.gpu.nvhpc-24.7
            cuda_sm = self.cfg.get_cuda_cc_template_value('cuda_sm_comma_sep')
            self.cfg.update('configopts', (
                'FCFLAGS="$FCFLAGS $CPPFLAGS'
                '    -Mrecursive -Mallocatable=03 -Mstack_arrays -Minfo=accel,inline'
                f'    -acc=gpu,verystrict -gpu={cuda_sm}"'
            ))

            # nvcc's plain -arch= flag only accepts a single target (unlike NVHPC's -gpu=
            # flag above), so build a real multi-arch fat binary via -gencode instead.
            cuda_ccs = self.cfg.get_cuda_cc_template_value('cuda_int_comma_sep')
            nvcc_gencode = ' '.join(
                f'-gencode arch=compute_{cc},code=sm_{cc}' for cc in cuda_ccs.split(',')
            )
            self.cfg.update('configopts', f'CUDAFLAGS="-ccbin=$CXX -O3 {nvcc_gencode}"')

            self.cfg.update('configopts', 'ICON_CFLAGS="$CFLAGS"')
            self.cfg.update('configopts', 'ICON_LDFLAGS="-Wl,--disable-new-dtags"')
            self.cfg.update('configopts', nvhpc_libs)
        elif comp_fam == toolchain.GCC:
            # Following config/mpim/bullseye.openmpi.gcc-14.2.0
            self.cfg.update('configopts', 'FCFLAGS="$FCFLAGS $CPPFLAGS"')
            self.cfg.update('configopts', 'ICON_CFLAGS="$CFLAGS"')
            # Set lock_assert=0 instead of MPI_MODE_NOCHECK for a MPI_Win_lock()
            self.cfg.update('configopts', 'ICON_FCFLAGS="$FCFLAGS -DDO_NOT_COMBINE_PUT_AND_NOCHECK"')
            self.cfg.update('configopts', 'ICON_OCEAN_FCFLAGS="$FCFLAGS -fno-tree-loop-vectorize"')
            self.cfg.update('configopts', gcc_libs)
        elif comp_fam == toolchain.INTELCOMP:
            # Following config/ecmwf/atos2020.intel-2025.0
            self.cfg.update('configopts', 'CFLAGS="$CFLAGS -qno-opt-dynamic-align"')
            self.cfg.update('configopts', 'ICON_CFLAGS="$CFLAGS -ftz"')
            self.cfg.update('configopts', 'ICON_BUNDLED_CFLAGS="-ftz"')
            # Set lock_assert=0 instead of MPI_MODE_NOCHECK for a MPI_Win_lock()
            self.cfg.update('configopts', (
                'ICON_FCFLAGS="'
                '    $FCFLAGS -ftz -fp-model=precise'
                '    -assume realloc_lhs'
                '    -DDO_NOT_COMBINE_PUT_AND_NOCHECK'
                '"'
            ))
            self.cfg.update('configopts', 'ICON_BUNDLED_FCFLAGS="-ftz"')
            self.cfg.update('configopts', (
                'ICON_OCEAN_FCFLAGS="'
                '    $FCFLAGS -ftz -fp-model=precise'
                '    -assume norealloc_lhs'
                '"'
            ))
            self.cfg.update('configopts', 'ICON_ECRAD_FCFLAGS="-qno-opt-dynamic-align -no-fma"')
            self.cfg.update('configopts', intel_libs)
        else:
            raise EasyBuildError("EB_ICON does not support toolchain compiler family '%s'", comp_fam)

    def configure_step(self):
        """Configure ICON build, setting toolchain-specific compiler flags and ./configure options."""
        comp_fam = self.toolchain.comp_family()

        self._check_dependencies()
        self._add_model_features(comp_fam)
        self._add_infrastructural_features(comp_fam)
        self._add_optimization_features(comp_fam)
        self._add_external_libraries()
        self._add_compiler_flags(comp_fam)

        super().configure_step()
