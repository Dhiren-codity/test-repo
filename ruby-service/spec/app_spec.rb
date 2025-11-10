# frozen_string_literal: true

require_relative '../app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content is missing' do
      post '/diff', { new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to match(/Missing old_content or new_content/)
    end

    it 'returns 400 when new_content is missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to match(/Missing old_content or new_content/)
    end

    it 'calls services and returns diff and review' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => 1 })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 80 })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq({ 'changes' => 1 })
      expect(body['new_code_review']).to eq({ 'score' => 80 })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files are missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end
  end

  describe 'Validation errors management' do
    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors).and_return(nil)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end