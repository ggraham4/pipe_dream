"""WO-56 schema probe (no outcome data): vsurfd tables, columns, one name-date."""
import sqlalchemy as sa, pandas as pd
eng = sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                       connect_args={"sslmode": "require", "connect_timeout": 120})
with eng.connect() as c:
    print(pd.read_sql(sa.text("select table_name from information_schema.tables where table_schema='optionm' and table_name like 'vsurfd%' order by 1"), c).table_name.tolist())
    print(pd.read_sql(sa.text("select column_name,data_type from information_schema.columns where table_schema='optionm' and table_name='vsurfd2010'"), c).to_string())
    print(pd.read_sql(sa.text("select * from optionm.vsurfd2010 where secid=101594 and date='2010-06-15' and days=30 order by cp_flag, delta"), c).to_string())
