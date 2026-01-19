




# source .venv/bin/activate
# pip freeze > requirements.txt
# uvicorn main:app --reload

how to refresh data:

1) Extrack AllAvailable busses: /extractBusRoutesData
2) Extract the bus services:/getBusServicesData?overwrite=true
3) Update busstops : extractBusStops
