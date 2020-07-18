# El Chapo

A serverless URL shortener that uses zappa to package a python/flask applicaiton into an AWS Lambda + API Gateway application while using AWS DynamoDB as the data store.

## Setup

- create virtual environment
```sh
virtualenv venv
```
- Activate virtual environment
```sh
source venv/bin/activate
```
- Install dependencies
```sh
pip install -r requirements.txt
```


## Deployment

- create an AWS account if you dont have one already and retrieve - public key and private key

- configure aws account on your terminal using the keys generated from step 1
```sh
aws configure
```

- Refer to zappa_settings.json and change the parameters accoring to your application.

- deploy your zappa application
```sh
zappa deploy <staging/production>
```
- you can configure your short url domain to route all requests to the URL that is given by zappa in the above step.

- If you have to update the application
```sh
zappa update <staging/production>
```

- To delete the deployment run
```sh
zappa undeploy <staging/production>
```

## Usage

- To create a new shortened URL
```sh
curl -XPOST '<short_url_domain>/c' -d '{"path": "shortpath", "webhook": "https://f81421ad32aa6b3f557cec14301e1296.m.pipedream.net?id=idtotrack", "redirect_url": "https://google.com"}' -H "content-type: application/json"
```
The webhook paramater here is optional.
- To retrieve the original URL from the short url
```sh
curl '<short_url_domain>/shortpath'
```

## Closing note
For more information regarding zappa and all the frameworks that it supports, please check out [zappa](https://github.com/Miserlou/Zappa)
