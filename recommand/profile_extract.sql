-- 用户画像临时表
create table user_profile_recommand as
select
    custref_no,
    case
        when FLOOR(
            MONTHS_BETWWEN(
                CURRENT_DATE(),
                TO_DATE(
                    FROM_UNIXTIME(UNIX_TIMESTAMP(birth_dt, 'yyyMMdd'))
                )
            ) / 12
        ) < '20' THEN 'A'
        when FLOOR(
            MONTHS_BETWWEN(
                CURRENT_DATE(),
                TO_DATE(
                    FROM_UNIXTIME(UNIX_TIMESTAMP(birth_dt, 'yyyMMdd'))
                )
            ) / 12
        ) < '30' THEN 'B'
        when FLOOR(
            MONTHS_BETWWEN(
                CURRENT_DATE(),
                TO_DATE(
                    FROM_UNIXTIME(UNIX_TIMESTAMP(birth_dt, 'yyyMMdd'))
                )
            ) / 12
        ) < '40' THEN 'C'
        when FLOOR(
            MONTHS_BETWWEN(
                CURRENT_DATE(),
                TO_DATE(
                    FROM_UNIXTIME(UNIX_TIMESTAMP(birth_dt, 'yyyMMdd'))
                )
            ) / 12
        ) < '50' THEN 'D'
        when FLOOR(
            MONTHS_BETWWEN(
                CURRENT_DATE(),
                TO_DATE(
                    FROM_UNIXTIME(UNIX_TIMESTAMP(birth_dt, 'yyyMMdd'))
                )
            ) / 12
        ) < '60' THEN 'E'
        ELSE 'F'
    END AS age,
    ROUND(self_income / 5000) AS self_income_round,
    case
        sex_id
        when 2 then 'F'
        ELSE 'M'
    END as sex
from
    (
        select
            *,
            row_number() over(
                partition by custref_no
                order by
                    etl_dt desc
            ) as rank
        from
            recommand_workspace.CDM_ADM_CUST_INFO_STAT_F
        where
            vaild_cust_flg = 1
    ) a
where
    a.rank = 1;

-- 创建商品画像
create table item_profile as
select
    base.str_id,
    base.str_nm,
    base.city_nm,
    base.cnty_nm,
    base.lng,
    base.lat,
    mapping_expanded.cat_nm as cat_nm1,
    meituan.cat_nm as cat_nm2
from
    (
        select
            *,
            row_number() over(
                partition by str_id
                order by
                    etl_dt desc
            )
        from
            recommand_workspace.o2o_new_gut_shop_base_third
        where
            str_sta = 'NORMAL'
    ) base
    left join (
        select
            cat_id,
            cat_nm,
            mt_cat_id
        from
            (
                select
                    *,
                    row_number() over(
                        partition by cat_id
                        order by
                            etl_dt desc
                    ) as rank
                from
                    recommand_workspace.o2o_new_gut_shop_category_mapping
            ) mapping_ranked
        where
            rank = 1
            and mt_cat_id is not null
            and mt_cat_id != '' LATERAL VIEW explode(split(mt_cat_ids, ',')) mapping_table as mt_cat_id
    ) mapping_expanded on base.cat_id = mapping_expanded.mt_cat_id
    left join recommand_workspace.o2o_new_gut_shop_category_meituan meituan on meituan.cat_id = cast(mapping_expanded.mt_cat_id as bigint);

-- 创建用户序列
create table user_seq_recommand as
select
    event,
    `time` event_time,
    distinct_id custref_no,
    regexp_extract(pg_url, 'shopId=(\\d+)', 1) as shopid,
    latitude user_latitude,
    longitude user_longitude,
    event_duration,
    btn_nm,
    cls_info
from
    cdm.c10_ods_events_xysh
where
    spm_a = '生活/本地优惠'
    and pg_nm = '本地优惠_美团门店详情页'
order by
    custref_no,
    event_time;

-- 创建 用户画像表
create table user_profile_norm_recommand as
select
    c.custref_no,
    c.age,
    c.sex,
    c.self_income_round
from
    (
        select
            custref_no,
            age,
            sex,
            self_income_round,
            row_number() over(
                partition by custref_no
            ) as rank
        from
            (
                (
                    select
                        *
                    from
                        user_profile_recommand
                ) a
                join (
                    select
                        *
                    from
                        user_seq_recommand
                ) b on a.custref_no = b.custref_no
            )
    ) c
where
    c.rank = 1;