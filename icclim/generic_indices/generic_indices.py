from __future__ import annotations

import abc
from functools import reduce

import numpy
import numpy as np
from jinja2 import Environment
from models.logical_operation import Operator
from xarray import DataArray
from xclim.core import datachecks
from xclim.core.calendar import select_time
from xclim.core.cfchecks import cfcheck_from_name
from xclim.core.options import MISSING_METHODS, MISSING_OPTIONS, OPTIONS
from xclim.core.units import convert_units_to, to_agg_units

from icclim.models.climate_index import ClimateIndex
from icclim.models.climate_variable import ClimateVariable
from icclim.models.frequency import Frequency
from icclim.models.index_config import IndexConfig
from icclim.models.user_index_config import LogicalOperation

# jinja_env = Environment(autoescape=True)
# todo could be a security issue to have autoescape=False (default)
#      but otherwise > and < are replaced by &gt and &lt
jinja_env = Environment()


class Indicator:
    identifier: str
    units: str
    standard_name: str
    long_name: str
    description: str
    cell_methods: str

    src_freq: Frequency
    short_name: str

    templated_properties = [
        "identifier",
        "units",
        "standard_name",
        "long_name",
        "description",
        "cell_methods",
    ]  # todo make it a decorator ?

    @abc.abstractmethod  # todo  is abc.abstractmethod really needed ?
    def __call__(self, *args, **kwargs):
        ...

    @abc.abstractmethod
    def preprocess(self, *args, **kwargs) -> list[DataArray]:
        ...

    @abc.abstractmethod
    def postprocess(self, *args, **kwargs) -> DataArray:
        ...


class ResamplingIndicator(Indicator):
    missing: str
    missing_options: dict | None

    def __init__(self, missing="from_context", missing_options=None):
        self.missing_options = missing_options
        self.missing = missing
        if self.missing == "from_context" and self.missing_options is not None:
            raise ValueError(
                "Cannot set `missing_options` with `missing` method being from context."
            )
        if self.missing_options:
            MISSING_METHODS[self.missing].validate(**self.missing_options)
        super().__init__()

    def datachecks(self, climate_vars: list[ClimateVariable], src_freq: str):
        if src_freq is None:
            return
        for climate_var in climate_vars:
            da = climate_var.study_da
            if "time" in da.coords and da.time.ndim == 1 and len(da.time) > 3:
                datachecks.check_freq(da, src_freq, strict=True)

    def cfcheck(self, climate_vars: list[ClimateVariable]):
        """Compare metadata attributes to CF-Convention standards.

        Default cfchecks use the specifications in `xclim.core.utils.VARIABLES`,
        assuming the indicator's inputs are using the CMIP6/xclim variable names
        correctly.
        Variables absent from these default specs are silently ignored.

        When subclassing this method, use functions decorated using
        `xclim.core.options.cfcheck`.
        """
        for da in climate_vars:
            try:
                cfcheck_from_name(str(da.name), da)
            except KeyError:
                # Silently ignore unknown variables.
                pass

    def preprocess(
        self,
        /,
        climate_vars: list[ClimateVariable],
        jinja_scope: dict,
        freq: str,
        indexer: dict,
        *args,
        **kwargs,
    ) -> list[ClimateVariable]:
        self.datachecks(climate_vars, freq)
        self.cfcheck(climate_vars)
        self.format(
            jinja_scope=jinja_scope,
            **kwargs,
        )
        if indexer:
            for climate_var in climate_vars:
                climate_var.study_da = select_time(climate_var.study_da, **indexer)
        return climate_vars

    def postprocess(
        self,
        result: DataArray,
        /,
        das: list[DataArray],
        freq: str,
        indexer: dict = None,
        *args,
        **kwargs,
    ):
        if self.missing == "skip":
            return self._handle_missing_values(
                freq=freq, indexer=indexer, in_data=das, out_data=result
            )
        for prop in self.templated_properties:
            result.attrs[prop] = getattr(self, prop)
        result.attrs["history"] = ""
        return result

    def format(self, /, jinja_scope, **kwargs):  # noqa ignore extra kwargs
        for property in self.templated_properties:
            template = jinja_env.from_string(
                getattr(self, property),  # todo instead get the localized version
                globals=jinja_scope,
            )
            setattr(self, property, template.render())

    def _handle_missing_values(
        self, in_data, freq: str, indexer: dict | None, out_data
    ):
        options = self.missing_options or OPTIONS[MISSING_OPTIONS].get(self.missing, {})
        # We flag periods according to the missing method. skip variables without a time
        # coordinate.
        miss = (
            MISSING_METHODS[self.missing].execute(
                da, freq, self.src_freq.pandas_freq, options, indexer
            )
            for da in in_data
            if "time" in da.coords
        )
        # Reduce by or and broadcast to ensure the same length in time
        # When indexing is used and there are no valid points in the last period,
        # mask will not include it
        mask = reduce(np.logical_or, miss)
        if isinstance(mask, DataArray) and mask.time.size < out_data[0].time.size:
            mask = mask.reindex(time=out_data[0].time, fill_value=True)
        return [out.where(~mask) for out in out_data]


class CountEventComparedToThreshold(ResamplingIndicator):
    # TODO: Add aliases to recognize common indices (heatwave, SU, tropical_night, etc).
    #       or just define catalogs (ecad, xclim, ettcdi) ?
    identifier = (
        "{{src_freq.units}}_when"
        "{% for i, input in enumerate(inputs) %}"
        "_{{input.short_name}}"
        "_{{operator.standard_name}}"
        "_{{input.threshold.standard_name}}"
        "{% if i != len(inputs) - 1 %}"
        "_and"  # todo make it configurable logical operator ? and | or | xor ?
        "{% endif%}"
        "{% endfor %}"
    )
    units = "{{src_freq.units}}"
    standard_name = (
        "number_of_{{src_freq.units}}_when"
        "{% for i, input in enumerate(inputs) %}"
        "_{{input.standard_name}}"
        "_{{operator.standard_name}}"
        "_{{input.threshold.standard_name}}"
        "{% if i != len(inputs) - 1 %}"
        "_and"  # todo make it configurable logical operator ? and | or | xor ?
        "{% endif%}"
        "{% endfor %}"
    )
    long_name = (
        "Number of {{src_freq.units}} when"
        "{% for i, input in enumerate(inputs) %}"
        " {{input.short_name}}"
        " {{operator.operand}}"
        " {{input.threshold.value}}"
        "{% if input.threshold.additional_metadata %}"
        " ({{input.threshold.additional_metadata}})"
        "{% endif%}"
        "{% if i != len(inputs) - 1 %}"
        " and"  # todo make it configurable logical operator ? and | or | xor ?
        "{% endif%}"
        "{% endfor %}"
        "."
    )
    description = (
        "Number of {{src_freq.units}} when"
        " {{output_freq}}"
        "{% for i, input in enumerate(inputs) %}"
        " {{input.long_name}} is"
        " {{operator.long_name}}"
        " {{input.threshold.value}}"
        "{% if input.threshold.additional_metadata %}"
        " ({{input.threshold.additional_metadata}})"
        "{% endif%}"
        "{% if i != len(inputs) - 1 %}"
        " and"  # todo make it configurable logical operator ? and | or | xor ?
        "{% endif%}"
        "{% endfor %}"
        "."
    )
    cell_methods = "time: sum over {{src_freq.units}}"

    operator: Operator

    def __init__(self, short_name: str, operator: LogicalOperation, **kwds):
        super().__init__(**kwds)
        self.operator = operator._operator
        self.input_variables = None
        # -- duct type to ClimateIndex (todo make it cleaner (remove ClimateIndex ?))
        self.short_name = short_name
        self.input_variables = None
        self.compute = None
        self.group = None

    def preprocess(
        self,
        /,
        climate_vars: list[ClimateVariable],
        frequency: Frequency,
        indexer: dict,
        *args,
        **kwargs,
    ) -> list[ClimateVariable]:
        # todo:
        #       probably unsafe to do `config.cf_variables[0]`
        #       in case config.cf_variables[1] (or others) have a != frequency
        inputs = list(map(lambda cf_var: cf_var.to_dict(self.src_freq), climate_vars))
        jinja_scope = {
            # todo localize these
            "inputs": inputs,
            "operator": self.operator,
            "output_freq": frequency.description,
            "np": numpy,
            "enumerate": enumerate,
            "len": len,
            "src_freq": self.src_freq,
        }
        return super().preprocess(
            climate_vars=climate_vars,
            jinja_scope=jinja_scope,
            freq=frequency.pandas_freq,
            indexer=frequency.indexer,
            *args,
            **kwargs,
        )

    def __call__(self, /, config: IndexConfig, *args, **kwargs) -> DataArray:
        # icclim  wrapper
        self.src_freq = config.cf_variables[0].cf_meta.frequency
        climate_vars = self.preprocess(
            frequency=config.frequency,
            indexer=config.frequency.indexer,
            climate_vars=config.cf_variables,
            *args,
            **kwargs,
        )
        result = self._compare_climate_vars_to_thresholds(
            climate_vars=climate_vars,
            freq=config.frequency.pandas_freq,
            operator=self.operator,
        )
        return self.postprocess(
            result,
            das=list(map(lambda cv: cv.study_da, climate_vars)),
            freq=config.frequency.pandas_freq,
        )

    def _compare_climate_vars_to_thresholds(
        self,
        /,
        climate_vars: list[ClimateVariable],
        operator: Operator,
        freq: str = "YS",
    ) -> DataArray:
        intermediary = [
            self._compare_climate_var_to_thresh(
                climate_var.study_da, operator, climate_var.threshold.value, freq
            )
            for climate_var in climate_vars
        ]
        return reduce(np.logical_and, intermediary)  # noqa

    def _compare_climate_var_to_thresh(
        self,
        data: DataArray,
        operator: Operator,
        thresholds: DataArray,
        freq: str = "YS",
    ) -> DataArray:
        # xclim index function
        # signature is not exact as parameters can be injected
        thresholds = convert_units_to(thresholds, data)
        res = operator(data, thresholds).resample(time=freq).sum(dim="time")
        return to_agg_units(res, data, "count")


class IndexCatalog:
    _catalog: dict[str, ClimateIndex]

    def __init__(self, catalog=None, **kwargs):
        if catalog:
            self._catalog = catalog
        else:
            self._catalog = kwargs

    def lookup(self, query: str) -> ClimateIndex | None:
        for k, v in self._catalog.items():
            if query == k or query == v.short_name:
                return v
        return None


GenericIndexCatalog = IndexCatalog(
    greater=CountEventComparedToThreshold(
        short_name="greater", operator=LogicalOperation.GREATER
    ),
    greater_or_equal=CountEventComparedToThreshold(
        short_name="greater_or_equal", operator=LogicalOperation.GREATER_OR_EQUAL
    ),
    lower=CountEventComparedToThreshold(
        short_name="lower", operator=LogicalOperation.LOWER
    ),
    lower_or_equal=CountEventComparedToThreshold(
        short_name="lower_or_equal", operator=LogicalOperation.LOWER_OR_EQUAL
    ),
    equal=CountEventComparedToThreshold(
        short_name="equal", operator=LogicalOperation.EQUAL
    ),
)


def days_where_studies_are_above_references(
    inputs: [ClimateVariable], freq: str = "YS"
):
    from functools import reduce

    # noqa -> ::map does not infer the proper type
    out: DataArray = map(lambda x: x.study_da > x.reference_da, inputs)  # noqa
    out = reduce(lambda a, b: np.logical_and(a, b), out)
    out = out.resample(time=freq).sum(dim="time")
    return to_agg_units(out, inputs[0].st, "count")


# # new indices (https://github.com/Ouranosinc/xclim/issues/1093)
# days_above_thresholds
# (scalar, per-gridcell scalars, percentile_doy, percentile_on_period, )
# # cwd, csu
# max_consecutive_days_above_scalar
# # csdi
# days_where_spell_is_above_day_of_year_percentiles
# # -- COUNT DAYS BELOW
# # fd
# days_below_scalar
# # tx10p
# days_below_day_of_year_percentiles
# # ?
# days_below_period_percentiles
# # new indices
# days_below_tensor
# # cdd, cfd
# max_consecutive_days_below_scalar
# # csdi
# days_where_spell_is_above_day_of_year_percentiles
# # -- SUM
# # hd17
# sum_scalar_exceedance
# # gd4
# sum_scalar_subceedance
# # -- Average
# # tx
# mean
# # sdii
# mean_scalar_exceedance
# # -- MIN
# # txn
# min
# # -- MAX
# # txx, rx1day
# max
# # -- COMPOSITE
# # WW, CW, WD, CD
# logical_and(index1, index2)
# # DTR
# mean_of_difference
# # vDTR
# mean_of_absolute_difference
# # ETR
# max(var1) - min(var2)
# #
#
# # TODO:
# #    - composite indices (DTR, vDTR, WW, CW...)
# #    - rxxpTOT
# #    - r5day
# #    - prcptot
# #    - handle units
