# -*- Coding: latin-1 -*-
#  Copyright CERFACS (http://cerfacs.fr/)
#  Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
"""
Main entry point of icclim.
This module expose the index API endpoint as long as a few other functions.
"""
from __future__ import annotations

import copy
import logging
import time
from datetime import datetime
from functools import reduce
from typing import Callable, Literal, Sequence
from warnings import warn

import xarray as xr
import xclim
from xarray.core.dataarray import DataArray
from xarray.core.dataset import Dataset
from xclim.core.utils import PercentileDataArray

from generic_indices.generic_indices import GenericIndexCatalog, Indicator
from icclim.ecad.ecad_functions import IndexConfig
from icclim.ecad.ecad_indices import EcadIndex, get_season_excluded_indices
from icclim.icclim_exceptions import InvalidIcclimArgumentError
from icclim.icclim_logger import IcclimLogger, Verbosity
from icclim.icclim_types import ThresholdType
from icclim.models.climate_index import ClimateIndex
from icclim.models.constants import ICCLIM_VERSION, VALID_PERCENTILE_DIMENSION
from icclim.models.frequency import Frequency, SliceMode
from icclim.models.index_group import IndexGroup
from icclim.models.netcdf_version import NetcdfVersion
from icclim.models.quantile_interpolation import QuantileInterpolation
from icclim.models.user_index_config import UserIndexConfig
from icclim.models.user_index_dict import UserIndexDict
from icclim.pre_processing.input_parsing import (
    InFileType,
    guess_var_names,
    read_dataset,
    guess_input_type,
    _get_threshold_var_name,
    _standardize_percentile_dim_name,
    _read_clim_bounds,
    InFileDictionary,
    InFileBaseType,
    build_study_da,
)
from icclim.user_indices.calc_operation import CalcOperation, compute_user_index
from models.climate_variable import ClimateVariable
from models.threshold import Threshold

log: IcclimLogger = IcclimLogger.get_instance(Verbosity.LOW)

HISTORY_CF_KEY = "history"
SOURCE_CF_KEY = "source"

def indices(
        index_group: Literal["all"] | str | IndexGroup | list[str],
        ignore_error: bool = False,
        **kwargs,
) -> Dataset:
    """
    Compute multiple indices at the same time.
    The input dataset(s) must include all the necessary variables.
    It can only be used with keyword arguments (kwargs)

    Parameters
    ----------
    index_group : "all" | str | IndexGroup | list[str]
        Either the name of an IndexGroup, a instance of IndexGroup or a list
        of index short names.
        The value "all" can also be used to compute every indices.
        Note that the input given by ``in_files`` must include all the necessary
        variables to compute the indices of this group.
    kwargs : Dict
        ``icclim.index`` keyword arguments.

    Returns
    -------
    xr.Dataset
        A Dataset with one data variable per index.

    .. notes
        If ``output_file`` is part of kwargs, the result is written in a single netCDF
        file, which will contain all the index results of this group.

    """
    if isinstance(index_group, list):
        indices = [EcadIndex.lookup(i) for i in index_group]
    elif index_group == IndexGroup.WILD_CARD_GROUP or (
        isinstance(index_group, str)
        and index_group.lower() == IndexGroup.WILD_CARD_GROUP.value
    ):
        indices = iter(EcadIndex)
    else:
        indices = IndexGroup.lookup(index_group).get_indices()
    out = None
    if "out_file" in kwargs.keys():
        out = kwargs["out_file"]
        del kwargs["out_file"]
    acc = []
    for i in indices:
        kwargs["index_name"] = i.short_name
        if ignore_error:
            try:
                acc.append(index(**kwargs))
            except Exception:
                warn(f"Could not compute {i.short_name}.")
        else:
            acc.append(index(**kwargs))
    ds: Dataset = xr.merge(acc)
    if out is not None:
        _write_output_file(
            result_ds=ds,
            input_time_encoding=ds.time.encoding,
            netcdf_version=kwargs.get("netcdf_version", NetcdfVersion.NETCDF4),
            file_path=out,
        )
    return ds


def indice(*args, **kwargs):
    """
    Deprecated proxy for `icclim.index` function.
    To be deleted in a futur version.
    """
    log.deprecation_warning(old="icclim.indice", new="icclim.index")
    return index(*args, **kwargs)

def index(
        in_files: InFileType,
        index_name: str | None = None,  # optional when computing user_indices
        var_name: str | Sequence[str] | None = None,
        slice_mode: SliceMode = Frequency.YEAR,
        time_range: Sequence[datetime | str ] | None = None,
        out_file: str | None = None,
        threshold: ThresholdType | Sequence[ThresholdType] = None,
        callback: Callable[[int], None] = log.callback,
        callback_percentage_start_value: int = 0,
        callback_percentage_total: int = 100,
        base_period_time_range: Sequence[datetime | str ] | None = None,
        window_width: int = 5,
        only_leap_years: bool = False,
        ignore_Feb29th: bool = False,
        interpolation: (
                str | QuantileInterpolation | None
        ) = QuantileInterpolation.MEDIAN_UNBIASED,
    out_unit: str | None = None,
    netcdf_version: str | NetcdfVersion = NetcdfVersion.NETCDF4,
    user_index: UserIndexDict | None = None,
    save_percentile: bool = False,
    logs_verbosity: Verbosity | str = Verbosity.LOW,
    # deprecated parameters
    indice_name: str = None,
    user_indice: UserIndexDict = None,
    transfer_limit_Mbytes: float = None,
) -> Dataset:
    """
    Main entry point for icclim to compute climate indices.

    Parameters
    ----------
    in_files : str | list[str] | Dataset | DataArray | InputDictionary,
        Absolute path(s) to NetCDF dataset(s), including OPeNDAP URLs,
        or path to zarr store, or xarray.Dataset or xarray.DataArray.
    index_name : str
        Climate index name.
        For ECA&D index, case insensitive name used to lookup the index.
        For user index, it's the name of the output variable.
    var_name : str | list[str] | None
        ``optional`` Target variable name to process corresponding to ``in_files``.
        If None (default) on ECA&D index, the variable is guessed based on the climate
        index wanted.
        Mandatory for a user index.
    slice_mode : SliceMode
        Type of temporal aggregation:
        The possibles values are ``{"year", "month", "DJF", "MAM", "JJA", "SON",
        "ONDJFM" or "AMJJAS", ("season", [1,2,3]), ("month", [1,2,3,])}``
        (where season and month lists can be customized) or any valid pandas frequency.
        A season can also be defined between two exact dates:
        ``("season", ("19 july", "14 august"))``.
        Default is "year".
        See :ref:`slice_mode` for details.
    time_range : list[datetime ] | list[str]  | tuple[str, str] | None
        ``optional`` Temporal range: upper and lower bounds for temporal subsetting.
        If ``None``, whole period of input files will be processed.
        The dates can either be given as instance of datetime.datetime or as string
        values. For strings, many format are accepted.
        Default is ``None``.
    out_file : str | None
        Output NetCDF file name (default: "icclim_out.nc" in the current directory).
        Default is "icclim_out.nc".
        If the input ``in_files`` is a ``Dataset``, ``out_file`` field is ignored.
        Use the function returned value instead to retrieve the computed value.
        If ``out_file`` already exists, icclim will overwrite it!
    threshold : float | list[float] | None
        ``optional`` User defined threshold for certain indices.
        Default depend on the index, see their individual definition.
        When a list of threshold is provided, the index will be computed for each
        thresholds.
    transfer_limit_Mbytes : float
        Deprecated, does not have any effect.
    callback : Callable[[int], None]
        ``optional`` Progress bar printing. If ``None``, progress bar will not be
        printed.
    callback_percentage_start_value : int
        ``optional`` Initial value of percentage of the progress bar (default: 0).
    callback_percentage_total : int
        ``optional`` Total percentage value (default: 100).
    base_period_time_range : list[datetime ] | list[str]  | tuple[str, str] | None
        ``optional`` Temporal range of the reference period on which percentiles are
        computed.
        When missing, the studied period is used to compute percentiles.
        The study period is either the dataset filtered by `time_range` or the whole
        dataset if  `time_range` is None.
        On temperature based indices relying on percentiles (TX90p, WSDI...), the
        overlapping period between `base_period_time_range` and the study period is
        bootstrapped.
        On indices not relying on percentiles, this parameter is ignored.
        The dates can either be given as instance of datetime.datetime or as string
        values.
        For strings, many format are accepted.
    window_width : int
        ``optional`` User defined window width for related indices (default: 5).
        Ignored for non related indices.
    only_leap_years : bool
        ``optional`` Option for February 29th (default: False).
    ignore_Feb29th : bool
        ``optional`` Ignoring or not February 29th (default: False).
    interpolation : str | QuantileInterpolation | None
        ``optional`` Interpolation method to compute percentile values:
        ``{"linear", "hyndman_fan"}``
        Default is "hyndman_fan", a.k.a type 8 or method 8.
        Ignored for non percentile based indices.
    out_unit : str | None
        ``optional`` Output unit for certain indices: "days" or "%" (default: "days").
    netcdf_version : str | icclim.models.netcdf_version.NetcdfVersion
        ``optional`` NetCDF version to create (default: "NETCDF3_CLASSIC").
    user_index : UserIndexDict
        ``optional`` A dictionary with parameters for user defined index.
        See :ref:`Custom indices`.
        Ignored for ECA&D indices.
    save_percentile : bool
        ``optional`` True if the percentiles should be saved within the resulting netcdf
         file (default: False).
    logs_verbosity : str | Verbosity
        ``optional`` Configure how verbose icclim is.
        Possible values: ``{"LOW", "HIGH", "SILENT"}`` (default: "LOW")
    indice_name : str | None
        DEPRECATED, use index_name instead.
    user_indice : dict | None
        DEPRECATED, use user_index instead.
    kwargs : dict
        Additional keyword arguments passed to xclim index function.

    """
    _setup(callback, callback_percentage_start_value, logs_verbosity, slice_mode)
    index_name, user_index = _handle_deprecated_params(
        index_name, indice_name, transfer_limit_Mbytes, user_index, user_indice
    )
    # -- Choose index to compute
    if user_index is None and index_name is None:
        raise InvalidIcclimArgumentError(
            "No index to compute."
            " You must provide either `user_index` to compute a customized index"
            " or `index_name` for one of the ECA&D indices."
        )
    if index_name is not None:
        if (ecad_index := EcadIndex.lookup(index_name)) is not None:
            index = ecad_index.climate_index
            if threshold is not None:
                # todo instead: warning ?
                #      and/or reroute to the corresponding generic index ?
                raise InvalidIcclimArgumentError(
                    "ECAD indices threshold cannot be "
                    "configured. Use a generic index "
                    "instead."
                )
        elif (generic_index := GenericIndexCatalog.lookup(index_name)) is not None:
            index = generic_index
        else:
            raise InvalidIcclimArgumentError(f"Unknown index {index_name}.")
    else:
        index = None
    sampling_frequency = Frequency.lookup(slice_mode)
    climate_vars = read_climate_vars(
        base_period_time_range,
        ignore_Feb29th,
        in_files,
        index,
        interpolation,
        only_leap_years,
        sampling_frequency,
        threshold,
        time_range,
        var_name,
        window_width,
    )
    config = IndexConfig(
        save_percentile=save_percentile,
        frequency=sampling_frequency,
        cf_variables=climate_vars,
        window=window_width,
        out_unit=out_unit,
        netcdf_version=NetcdfVersion.lookup(netcdf_version),
        interpolation=interpolation,
        callback=callback,
        index=index,
    )
    if user_index is not None:
        result_ds = _compute_custom_climate_index(config=config, user_index=user_index)
    else:
        _check_valid_config(index, config)
        result_ds = _compute_standard_climate_index(
            config=config,
            climate_index=index,
            initial_history="",
            initial_source="",
            # initial_history=input_dataset.attrs.get(HISTORY_CF_KEY, None),
            # initial_source=input_dataset.attrs.get(SOURCE_CF_KEY, None),
        )
    if reset := result_ds.attrs.get("reset_coords_dict", None):
        result_ds = result_ds.rename(reset)
        del result_ds.attrs["reset_coords_dict"]
    if out_file is not None:
        _write_output_file(
            result_ds, input_dataset.time.encoding, config.netcdf_version, out_file
        )
    callback(callback_percentage_total)
    log.ending_message(time.process_time())
    return result_ds


def read_climate_vars(
        base_period_time_range,
        ignore_Feb29th,
        in_files,
        index,
        interpolation,
        only_leap_years: bool,
        sampling_frequency: Frequency,
        threshold,
        time_range,
        var_names,
        window_width: int,
) -> list[ClimateVariable]:
    # TODO [refacto] move to input_parsing
    # TODO [metadata]: all these pre-processing operations should probably be added in history
    #       metadata or provenance.
    #       It could be a property in CfVariable which will be reused when we
    #       update the metadata of the index, at the end.
    #       We could have a ProvenanceService "taking notes" of each operation that must be
    #       logged into the output netcdf/provenance/metadata
    dico = to_readable_input(in_files, var_names, index, threshold)
    return read_dictionary(base_period_time_range, ignore_Feb29th, dico,
                           index, interpolation, only_leap_years, sampling_frequency,
                           threshold, time_range, window_width)


def to_readable_input(
        in_files: InFileType,
        var_names: Sequence[str],
        index: ClimateIndex,
        threshold: ThresholdType,
) -> InFileDictionary:
    # TODO [refacto] move to input_parsing
    if isinstance(in_files, dict):
        if var_names is not None:
            warn("`var_name` is ignored, `in_files` keys are used instead.")
        return in_files
    if not isinstance(in_files, dict):
        input_dataset = read_dataset(in_files, index, var_names)
        var_names = guess_var_names(input_dataset, index, var_names)
        return {
            var_name: {
                "study":      input_dataset[var_name],
                "thresholds": threshold,
            }
            for var_name in var_names
        }


def read_dictionary(base_period_time_range, ignore_Feb29th, in_files:dict,
        index, interpolation, only_leap_years, sampling_frequency, threshold,
        time_range, window_width):
    # TODO [refacto] move to input_parsing
    # TODO [refacto] add types to parameters and output
    climate_vars = []
    for climate_var_name, climate_var_data in in_files.items():
        if isinstance(climate_var_data, dict):
            study_ds = read_dataset(
                climate_var_data["study"], index, climate_var_name
            )
            cf_meta = guess_input_type(study_ds[climate_var_name])
            # todo: deprecate climate_var_data.get("per_var_name", None) for threshold_var_name
            if climate_var_data.get("thresholds", None) is not None:
                climate_var_thresh = _read_thresholds(
                    climate_var_name,
                    climate_var_data.get("thresholds", None),
                    climate_var_data.get("threshold_var_name", None),
                    climate_var_data.get("climatology_bounds", None),
                )
            else:
                climate_var_thresh = threshold
        else:
            climate_var_data: InFileBaseType
            study_ds = read_dataset(climate_var_data, index, climate_var_name)
            cf_meta = guess_input_type(study_ds[climate_var_name])
            climate_var_thresh = threshold
        study_da = build_study_da(
            study_ds[climate_var_name],
            time_range,
            ignore_Feb29th,
            sampling_frequency,
        )
        threshold = Threshold(
            threshold=climate_var_thresh,
            study_da=study_da,
            units=study_da.attrs.get("units", cf_meta.units),
            window=window_width,
            only_leap_years=only_leap_years,
            interpolation=interpolation,
            base_period_time_range=base_period_time_range,
            sampling_frequency=sampling_frequency,
        )
        climate_vars.append(
            ClimateVariable(
                name=climate_var_name,
                cf_meta=cf_meta,
                study_da=study_da,
                threshold=threshold
            )
        )
    return climate_vars

def _read_thresholds(
        climate_var_name: str,
        thresh: InFileBaseType | float | Sequence[float],
        threshold_var_name: str,
        climatology_bounds: Sequence[str, str],
) -> float | Sequence | DataArray | PercentileDataArray:
    # TODO [refacto] move to input_parsing
    if isinstance(thresh, (str, float, int, list, tuple)):
        return thresh
    per_ds = read_dataset(thresh, index=None)
    threshold_var_name = _get_threshold_var_name(
        per_ds, threshold_var_name, climate_var_name
    )
    da = per_ds[threshold_var_name].rename(f"{climate_var_name}_thresholds")
    if is_percentile_data:
        return PercentileDataArray.from_da(
            _standardize_percentile_dim_name(da),
            _read_clim_bounds(climatology_bounds, da),
        )
    return da


def is_percentile_data(da) -> bool:
    return reduce(lambda x, y: x or (y in da.dims), VALID_PERCENTILE_DIMENSION, False)


def _write_output_file(
        result_ds: xr.Dataset,
        input_time_encoding: dict,
        netcdf_version: NetcdfVersion,
        file_path: str,
) -> None:
    """Write `result_ds` to a netCDF file on `out_file` path."""
    if input_time_encoding:
        time_encoding = {
            "calendar": input_time_encoding.get("calendar"),
            "units": input_time_encoding.get("units"),
            "dtype": input_time_encoding.get("dtype"),
        }
    else:
        time_encoding = {"units": "days since 1850-1-1"}
    result_ds.to_netcdf(
        file_path, format=netcdf_version.value, encoding={"time": time_encoding},
    )


def _handle_deprecated_params(
    index_name, indice_name, transfer_limit_Mbytes, user_index, user_indice
) -> tuple[str, UserIndexDict]:
    if indice_name is not None:
        log.deprecation_warning(old="indice_name", new="index_name")
        index_name = indice_name
    if user_indice is not None:
        log.deprecation_warning(old="user_indice", new="user_index")
        user_index = user_indice
    if transfer_limit_Mbytes is not None:
        log.deprecation_warning(old="transfer_limit_Mbytes")
    return index_name, user_index


def _setup(callback, callback_start_value, logs_verbosity, slice_mode):
    # make xclim input daily check a warning instead of an error
    # TODO: it might be safer to feed a context manager which will setup
    #       and teardown these confs
    xclim.set_options(data_validation="warn")
    # keep attributes through xarray operations
    xr.set_options(keep_attrs=True)
    log.set_verbosity(logs_verbosity)
    log.start_message()
    callback(callback_start_value)


def _compute_custom_climate_index(
    config: IndexConfig, user_index: UserIndexDict
) -> Dataset:
    logging.info("Calculating user index.")
    result_ds = Dataset()
    deprecated_name = user_index.get("indice_name", None)
    if deprecated_name is not None:
        user_index["index_name"] = deprecated_name
        del user_index["indice_name"]
        log.deprecation_warning("indice_name", "index_name")
    user_indice_config = UserIndexConfig(
        **user_index,
        freq=config.frequency,
        cf_vars=config.cf_variables,
        is_percent=config.is_percent,
        save_percentile=config.save_percentile,
    )
    user_indice_da = compute_user_index(user_indice_config)
    user_indice_da.attrs["units"] = _get_unit(config.out_unit, user_indice_da)
    if user_indice_config.calc_operation is CalcOperation.ANOMALY:
        # with anomaly time axis disappear
        result_ds[user_indice_config.index_name] = user_indice_da
        return result_ds
    user_indice_da, time_bounds = config.frequency.post_processing(user_indice_da)
    result_ds[user_indice_config.index_name] = user_indice_da
    result_ds["time_bounds"] = time_bounds
    return result_ds


def _get_unit(output_unit: str | None, da: DataArray) -> str | None:
    da_unit = da.attrs.get("units", None)
    if da_unit is None:
        if output_unit is None:
            warn(
                "No unit computed or provided for the index was found."
                " Use out_unit parameter to add one."
            )
            return ""
        else:
            return output_unit
    else:
        return da_unit


def _compute_standard_climate_index(
    climate_index: Indicator,
    config: IndexConfig,
    initial_history: str | None,
    initial_source: str,
) -> Dataset:
    def compute(threshold: float | None = None):
        conf = copy.copy(config)
        if threshold is not None:
            conf.scalar_thresholds = threshold
        if config.frequency.time_clipping is not None:
            # xclim missing values checking system will not work with clipped time
            with xclim.set_options(check_missing="skip"):
                res = climate_index.compute(conf)
        else:
            res = climate_index(conf)  # todo need to merge ClimateIndex and Indicator
        if isinstance(res, tuple):
            return res
        else:
            return (res, None)

    logging.info(f"Calculating climate index: {climate_index.short_name}")
    result_da, percentiles_da = compute()
    result_da = result_da.rename(climate_index.short_name)
    result_da.attrs["units"] = _get_unit(config.out_unit, result_da)
    if config.frequency.post_processing is not None:
        resampled_da, time_bounds = config.frequency.post_processing(result_da)
        result_ds = resampled_da.to_dataset()
        if time_bounds is not None:
            result_ds["time_bounds"] = time_bounds
            result_ds.time.attrs["bounds"] = "time_bounds"
    else:
        result_ds = result_da.to_dataset()
    if percentiles_da is not None:
        result_ds = xr.merge([result_ds, percentiles_da])
    history = _build_history(result_da, config, initial_history, climate_index)
    result_ds = _add_ecad_index_metadata(
        result_ds, climate_index, history, initial_source
    )
    return result_ds


def _add_ecad_index_metadata(
        result_ds: Dataset, computed_index: Indicator, history: str,
        initial_source: str,
) -> Dataset:
    result_ds.attrs.update(
        dict(
            title=computed_index.short_name,
            references="ATBD of the ECA&D indices calculation"
            " (https://knmi-ecad-assets-prd.s3.amazonaws.com/documents/atbd.pdf)",
            institution="Climate impact portal (https://climate4impact.eu)",
            history=history,
            source=initial_source if initial_source is not None else "",
            Conventions="CF-1.6",
        )
    )
    result_ds.lat.encoding["_FillValue"] = None
    result_ds.lon.encoding["_FillValue"] = None
    return result_ds


def _build_history(
    result_da: DataArray,
    config: IndexConfig,
    initial_history: str | None,
    indice_computed: Indicator,
) -> str:
    if initial_history is None:
        # get xclim history
        initial_history = result_da.attrs[HISTORY_CF_KEY]
    else:
        # append xclim history
        initial_history = f"{initial_history}\n{result_da.attrs['history']}"
    del result_da.attrs[HISTORY_CF_KEY]
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = result_da.time[0].dt.strftime("%m-%d-%Y").data[()]
    end_time = result_da.time[-1].dt.strftime("%m-%d-%Y").data[()]
    return (
        f"{initial_history}\n"
        f" [{current_time}]"
        f" Calculation of {indice_computed.identifier}"
        f" index ({config.frequency.description})"
        f" from {start_time} to {end_time}"
        f" - icclim version: {ICCLIM_VERSION}"
    )


def _check_valid_config(index: ClimateIndex, config: IndexConfig):
    if index in get_season_excluded_indices() and config.frequency.indexer is not None:
        raise InvalidIcclimArgumentError(
            "Indices computing a spell cannot be computed on un-clipped season for now."
            " Instead, you can use a clipped_season like this:"
            "`slice_mode=['clipped_season', [12,1,2]]` (example of a DJF season)."
            " However, it will NOT take into account spells beginning before the season"
            " start!"
        )
